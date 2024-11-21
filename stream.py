#!/usr/bin/env python

import argparse
import os
import re
import serial
import serial.tools.list_ports
import subprocess
import sys
import threading
import time
import tkinter as tk

from grblmessages import grbl_errors
# from grblmessages import grbl_alarm

from colorama import init, Fore, Style
init()


# --------------------- Параметры ------------------------------------

RX_BUFFER_SIZE = 128    # Размер буфера (байт)
BAUD_RATE = 115200      # Скорость порта (байт/сек)
REPORT_INTERVAL = 1.0   # Периодичность (сек, не менее 0.20) запросов состояния (?)
MAX_ERRORS = 3          # Прерывать программу после N ошибок

port = serial.tools.list_ports.comports()
ports = []
for port in serial.tools.list_ports.comports():
    ports.append(port.name)
if len(ports) == 0:
    print(Fore.RED + "\n!!! Подключение GRBL отсутствует !!!\n" + Style.RESET_ALL)
    exit()

if os.name == 'posix':                          # параметры для Linux
    DEVICE = f'/dev/{ports[0]}'
    PATH_PLAYER = '/usr/bin/mpv'                # путь к проигрывателю
    PLAYER_OPTIONS="--no-terminal"              # параметры проигрывателя
    PATH_SOUND_1 = f'{os.getcwd()}/alarm.oga'   # путь к звуковому файлу
    PATH_SOUND_2 = f'{os.getcwd()}/click.ogg'
    PATH_STAT = f'{os.getcwd()}/stat.txt'       # путь к файлу статистики

else:                           # Windows
    DEVICE = f'{ports[0]}'
    PATH_PLAYER = 'c:\\mpv\\mpv.com'
    PLAYER_OPTIONS="--no-terminal"
    PATH_SCRIPT = os.path.realpath(__file__)
    PATH_SOUND_1 = re.findall(r'.*\\', text)[0] + 'alarm.oga'
    PATH_SOUND_2 = re.findall(r'.*\\', text)[0] + 'click.ogg'
    PATH_STAT = re.findall(r'.*\\', text)[0] + 'stat.txt'

# --------------------------------------------------------------------


# Передача аргументов сценарию
parser = argparse.ArgumentParser(description='Stream g-code file to grbl', add_help=False)
parser.add_argument('gcode_file', type=argparse.FileType('r'), help='g-code filename to be streamed')
parser.add_argument('-p', '--port', type=str, action='store', default=DEVICE, help='serial device path')
parser.add_argument('-v', '--verbose', action='store_true', default=False, help='suppress output text')
parser.add_argument('-s', '--simple', action='store_true', default=False, help='simple streaming mode')
parser.add_argument('-c', '--check', action='store_true', default=False, help='stream in check mode')
parser.add_argument('-r', '--repeats', type=int, action='store', default=1, help='repeat programm')
parser.add_argument('-d', '--pieces_distance', type=int, action='store', default=600, help='distance between pieces, mm')
parser.add_argument('-y', '--y_beep', type=int, action='store', default=0, help='y position for signal, mm')
parser.add_argument('-l', '--laser', type=int, action='store', default=None, help='replace laser power, %')
parser.add_argument('-f', '--speed', type=int, action='store', default=None, help='replace speed G1, mm/min')
parser.add_argument('-h', '--home', action='store_true', default=False, help='home before start')
parser.add_argument('-x', '--home_cycles', type=int, action='store', default=0, help='home after n cycles')

args = parser.parse_args()

file = args.gcode_file
gcode_name = re.sub(r'(\s+)', '_', file.name)
gcode_name = re.sub(r'(.*)(\\|/)', '', gcode_name)
for count, _ in enumerate(file):
    pass
lines_in_file = count + 1
file_size = os.path.getsize(file.name)

verbose = True if args.verbose else False

y_beep_position = args.y_beep if args.y_beep else None

def homing():
    last_report_len = 0
    print(f'Homing axes...', end='')
    ser.write(b"$H\n")
    while 1:
        grbl_out = ser.readline().decode().strip()
        clear_len = last_report_len - len(grbl_out)
        last_report_len = len(grbl_out)
        if grbl_out.lower().strip() == 'ok':
            print(f" >>> {grbl_out}{' '*clear_len}\n")
            break

# Отдельный процесс отправки запросов состояния '?'
def status_request():
    while is_run:
      ser.write(b'?')
      time.sleep(REPORT_INTERVAL)

# Текущие координаты осей из статуса GRBL
def position_from_status(state):
    # try:
    temp = re.search(r'WPos(.*?)(\|)', state, re.IGNORECASE).group()
    temp = temp[5:-1]
    coords = temp.split(',')
    x, y, _ = map(float, coords)
    return x, y

# Перемещения осей из строки gcode
def data_from_gcode(line):
    if ('G1' in line.upper() or 'G0' in line.upper()) and 'X' in line.upper():
        x_move = re.search(r'X(-?)(\d+)(\.?)(\d*)', line.upper()).group()    # 'X-28.731'
        x_move = float(x_move[1:])
    else: x_move = 0
    if ('G1' in line.upper() or 'G0' in line.upper()) and 'Y' in line.upper():
        y_move = re.search(r'Y(-?)(\d+)(\.?)(\d*)', line.upper()).group()    # 'Y10'
        y_move = float(y_move[1:])
    else: y_move = 0
    xy_move = (x_move**2 + y_move**2)**0.5
    if 'G1' in line.upper() and 'S' in line.upper():
        s = re.search(r'S(\d+)', line.upper()).group()    # 'S800'
        s_power = int(s[1:])
        s_move = s_power * xy_move
    else:
        s_move = 0
        s_power = 0
    if 'G1' in line.upper() and 'F' in line.upper():
        f_speed = re.search(r'F(\d+)', line.upper()).group()    # 'F2000'
        f_speed = int(f_speed[1:])
    else:
        f_speed = None
    return x_move, y_move, xy_move, f_speed, s_power, s_move

def beep(num=1):
    if not os.path.exists(PATH_PLAYER):
        print(f'Проигрыватель не найден по указанному пути {PATH_PLAYER}\n')
        return
    PATH_SOUND = PATH_SOUND_1 if num == 1 else PATH_SOUND_2
    if os.path.exists(PATH_SOUND):
        subprocess.Popen([PATH_PLAYER, PLAYER_OPTIONS, PATH_SOUND])
    else:
        print(f'Звуковой файл не найден по указанному пути {PATH_SOUND}\n')
        return

# Дата и время в читабельном формате
def date_time(unix_time=time.time()):
    t = time.localtime(unix_time)
    c_time = time.strftime("%H:%M:%S %d-%m-%Y", t)
    return c_time

def read_output():
    while 1:
        grbl_out = ser.readline().decode().strip()
        if grbl_out:
            break
    return grbl_out

# Запись статистики в файл
def add_stat(start_time_cycle, pieces_cycle_count, x_move, y_move, average_power):
    line = f'{int(start_time_cycle)} {int(time.time())} {gcode_name} {pieces_cycle_count} {int(x_move)} {int(y_move)} {int(average_power)} {id}'
    with open(PATH_STAT, 'a') as file_stat:
        file_stat.write(f'{line}\n')

# Считывание статистики из файла
def get_stat():
    stat_time = 0
    stat_pieces = 0
    stat_move_x = 0
    stat_move_y = 0
    stat_power = 0
    file = open(PATH_STAT, 'r')
    for line in file:
        data = re.split('\s+', line.strip())
        if len(data) > 6:
            stat_time += int(data[1]) - int(data[0]) # sec
            stat_pieces += int(data[3])
            stat_move_x += int(data[4]) # mm
            stat_move_y += int(data[5]) # mm
            # stat_power += int(data[6]) * (int(data[4])**2 + int(data[5])**2) **0.5 # by x,y moves
            stat_power += int(data[6]) * (int(data[1]) - int(data[0])) # by time
    file.close()
    # stat_power = int(stat_power / ((stat_move_x**2 + stat_move_y**2) **0.5))
    stat_power = int(stat_power / stat_time)
    return stat_time, stat_pieces, stat_move_x, stat_move_y, stat_power

# ----------- tkinter --------------
def cycle_resume():
    # print('Resume')
    ser.write(b'~')

def cycle_hold():
    # print('Hold')
    ser.write(b'!')

def soft_reset():
    # print('Soft-Reset')
    ser.write(b"\x18")

# SPEED
def override_speed_reset():
    ser.write(b"\x90")
    label_speed['text'] = '+0%'

def override_speed(num):
    current_value = int(label_speed['text'][:-1])
    new_value = int(current_value + num)
    if new_value >= -90 and new_value <= 100:
        if num == 10: ser.write(b"\x91")
        if num == -10: ser.write(b"\x92")
        if num == 1: ser.write(b"\x93")
        if num == -1: ser.write(b"\x94")
        if new_value >= 0:
            label_speed['text'] = f'+{new_value}%'
        else:
            label_speed['text'] = f'{new_value}%'

# LASER
def override_laser_reset():
    ser.write(b"\x99")
    label_laser['text'] = '+0%'

def override_laser(num):
    current_value = int(label_laser['text'][:-1])
    new_value = int(current_value + num)
    if new_value >= -90 and new_value <= 100:
        if num == 10: ser.write(b"\x9A")
        if num == -10: ser.write(b"\x9B")
        if num == 1: ser.write(b"\x9C")
        if num == -1: ser.write(b"\x9D")
        if new_value >= 0:
            label_laser['text'] = f'+{new_value}%'
        else:
            label_laser['text'] = f'{new_value}%'

def last_cycle():
    global is_last_cycle
    global button_last_cycle
    if not is_last_cycle:
        is_last_cycle = True
        button_last_cycle.configure(bg="red", fg="white")
    else:
        is_last_cycle = False
        button_last_cycle.configure(bg="yellow", fg="black")

def last_piece():
    global button_last_cycle
    global button_last_piece
    global is_last_piece
    global is_last_cycle
    if not is_last_piece:
        is_last_piece = True
        is_last_cycle = True
        button_last_cycle.configure(bg="red", fg="white")
        button_last_piece.configure(bg="red", fg="white")
    else:
        is_last_piece = False
        is_last_cycle = False
        button_last_cycle.configure(bg="yellow", fg="black")
        button_last_piece.configure(bg="yellow", fg="black")
    
def gui():
    global window
    global button_last_cycle
    global button_last_piece
    
    window = tk.Tk()
    window.title('GRBL Control')
    window.geometry('260x505+100+0')
    
    frame_c = tk.Frame(master=window)
    frame_c.grid(row=8, column=2)

    button_resume = tk.Button(master=frame_c, text="ПРОДОЛЖИТЬ", width=15, height=3, bg="green", fg="white", command=cycle_resume)
    button_resume.grid(row=0, column=0)
    button_hold = tk.Button(master=frame_c, text="ПАУЗА", width=15, height=3, bg="red", fg="white", command=cycle_hold)
    button_hold.grid(row=0, column=1)

    label_speed = tk.Label(master=frame_c, text='+0%', width=15, height=3)
    label_speed.grid(row=1, column=0)
    label_laser = tk.Label(master=frame_c, text='+0%', width=15, height=3)
    label_laser.grid(row=1, column=1)

    button_speed_inc10 = tk.Button(master=frame_c, text="СКОРОСТЬ +10%", width=15, height=3, bg="blue", fg="white", command=lambda: override_speed(10))
    button_speed_inc10.grid(row=2, column=0)
    button_laser_inc10 = tk.Button(master=frame_c, text="ЛАЗЕР +10%", width=15, height=3, bg="blue", fg="white", command=lambda: override_laser(10))
    button_laser_inc10.grid(row=2, column=1)

    button_speed_inc1 = tk.Button(master=frame_c, text="СКОРОСТЬ +1%", width=15, height=3, bg="blue", fg="white", command=lambda: override_speed(1))
    button_speed_inc1.grid(row=3, column=0)
    button_laser_inc1 = tk.Button(master=frame_c, text="ЛАЗЕР +1%", width=15, height=3, bg="blue", fg="white", command=lambda: override_laser(1))
    button_laser_inc1.grid(row=3, column=1)

    button_speed_reset = tk.Button(master=frame_c, text="СБРОС\nСКОРОСТИ", width=15, height=3, bg="green", fg="white", command=override_speed_reset)
    button_speed_reset.grid(row=4, column=0)
    button_laser_reset = tk.Button(master=frame_c, text="СБРОС\nМОЩНОСТИ\nЛАЗЕРА", width=15, height=3, bg="green", fg="white", command=override_laser_reset)
    button_laser_reset.grid(row=4, column=1)

    button_speed_dec1 = tk.Button(master=frame_c, text="СКОРОСТЬ -1%", width=15, height=3, bg="blue", fg="white", command=lambda: override_speed(-1))
    button_speed_dec1.grid(row=5, column=0)
    button_laser_dec1 = tk.Button(master=frame_c, text="ЛАЗЕР -1%", width=15, height=3, bg="blue", fg="white", command=lambda: override_laser(-1))
    button_laser_dec1.grid(row=5, column=1)

    button_speed_dec10 = tk.Button(master=frame_c, text="СКОРОСТЬ -10%", width=15, height=3, bg="blue", fg="white", command=lambda: override_speed(-10))
    button_speed_dec10.grid(row=6, column=0)
    button_laser_dec10 = tk.Button(master=frame_c, text="ЛАЗЕР -10%", width=15, height=3, bg="blue", fg="white", command=lambda: override_laser(-10))
    button_laser_dec10.grid(row=6, column=1)

    button_last_cycle = tk.Button(master=frame_c, text="ПОСЛЕДНИЙ\nЦИКЛ", width=15, height=3, bg="yellow", fg="black", command=last_cycle)
    button_last_cycle.grid(row=7, column=0)
    button_last_piece = tk.Button(master=frame_c, text="ПОСЛЕДНЯЯ\nДЕТАЛЬ", width=15, height=3, bg="yellow", fg="black", command=last_piece)
    button_last_piece.grid(row=7, column=1)
    
    # soft_reset_button = tk.Button(master=frame_c, text="SOFT-RESET", width=15, height=3, bg="red", fg="yellow", command=soft_reset)
    # soft_reset_button.pack()

    window.mainloop()
# -------------------------------------------------


# Вывод общей статистики при запуске сценария
if os.path.exists(PATH_STAT):
    stat = get_stat()
    print(Fore.YELLOW + f"\n-------- ОБЩАЯ СТАТИСТИКА --------\n")
    print(f"Время работы:          {int(stat[0]/(1*60*60))} ч")
    print(f"Деталей обработано:    {stat[1]} шт")
    print(f"Перемещения оси X:     {int(stat[2]/1000)} м")
    print(f"Перемещения оси Y:     {int(stat[3]/1000)} м")
    print(f"Перемещений с лазером: {int(stat[4]/10)} %")
    print(f"" + Style.RESET_ALL)

print(f"\n----------- ПАРАМЕТРЫ ------------\n")
print(f"Порт:              {DEVICE}")
print(f"Файл Gcode:        {file.name}")
if args.speed: print(f"Скорость оси X:    {args.speed} мм/мин")
if args.laser: print(f"Мощность лазера:   {args.laser} %")
print(f"Количество циклов: {args.repeats}")
print(f"Между деталями:    {args.pieces_distance} мм")
if y_beep_position: print(f"Звуковой сигнал Y: {y_beep_position} мм")

if args.simple:
    print(Fore.RED + f"Режим:             Simple streaming (может вызывать остановки в работе)" + Style.RESET_ALL)
else:
    # print(f"Режим:             Agressive streaming")
    pass


# Ввод имени для статистики
id = input(f'\nВведите Ваш ID или имя и нажмите Enter: ')
id = id.strip().upper()
id = re.sub(r'(\s+)', '_', id)

repeats_count = 0
pieces_count = 0
start_time_program = time.time()
last_time = 0 if args.repeats == 1 else 30*60   # Смотреть записи не старше 30 минут
# Продолжить отсчёт после короткой остановки
if os.path.exists(PATH_STAT):
    with open(PATH_STAT, 'r') as file_stat:
        lines = file_stat.readlines()
    for line in reversed(lines):
        data = re.split('\s+', line.strip())
        if (len(data)>7 and data[7]==id) or (len(data)<8 and id==''):
            if (int(data[1]) > (start_time_program-last_time)) and (data[2] == gcode_name):
                repeats_count += 1
                pieces_count += int(data[3])
                start_time_program = int(data[0])
            else:
                break


# Инициализация подклюения к GRBL
print(f'\nВремя запуска: {date_time(start_time_program)}\n')
print(f"Порт {args.port}      >>> Initializing Grbl...", end='')
ser = serial.Serial(args.port, BAUD_RATE, timeout=5, write_timeout=0)
grbl_out = ser.readline().decode().strip()
print(f" >>> {grbl_out}")
ser.write(b"\r\n\r\n")
time.sleep(1)
ser.flushInput()
print(f'SoftReset...   >>> 0x18 >>>', end='')
ser.write(b"\x18")
grbl_out = read_output()
print(f' {grbl_out.split("[")[0]}')

# Симуляция выполнения (Check mode)
if args.check:
    time.sleep(1)
    ser.write(b"$C\n")
    grbl_out = ser.readline().decode().strip()
    print(Fore.CYAN + f"Check-Mode...  >>> $C   >>> {grbl_out}" + Style.RESET_ALL)

    if 'error' in grbl_out.lower():
        print(Fore.RED + "  Failed to set Grbl check-mode. Aborting..." + Style.RESET_ALL)
        quit()
    time.sleep(3)

# Панель управления прошивкой во время работы
timerThread_gui = threading.Thread(target=gui)
timerThread_gui.daemon = True
timerThread_gui.start()

# Калибровка осей перед исполнением gcode
if args.home and not args.check:
    homing()
time.sleep(1)


# Процесс отправки запросов состояния (?)
timerThread = threading.Thread(target=status_request)
timerThread.daemon = True
is_run = True
timerThread.start()


is_last_cycle = False
is_last_piece = False

print('\n')
# Циклическая обработка gcode
while repeats_count < args.repeats:
    start_time_cycle = time.time()
    pieces_cycle_count = 0
    x_move_cycle_count = 0
    y_move_cycle_count = 0
    xy_move_cycle_count = 0
    s_cycle_count = 0
    errors_count = 0
    last_report_len = 0

    file.seek(0) # Start read file from begin

    beep_switch = True if y_beep_position else False

    # Простой способ отправки команд (без буфера)
    if args.simple:
        # Send settings file via simple call-response streaming method. Settings must be streamed
        # in this manner since the EEPROM accessing cycles shut-off the serial interrupt.

        l_count = 0
        for line in file:
            l_count += 1 # Iterate line counter
            x, y, xy, f, s, sxy = data_from_gcode(line)

            # Сохранить начальную позию для следующего цикла
            if 'G0' in line.upper() and x and y:
                start_position = line

            # Звуковой сигнал, если надена метка ; beep
            if '; beep' in line.lower():
                beep(1)

            # Счётчики деталей
            if 'G1' in line.upper() and not s and y >= args.pieces_distance:
                pieces_count += 1
                pieces_cycle_count += 1
                if is_last_piece:
                    break

            # Статистика
            if 'G1' in line.upper() or 'G0' in line.upper():
                x_move_cycle_count += abs(x)
                y_move_cycle_count += abs(y)
                xy_move_cycle_count += xy
                s_cycle_count += sxy

            # Подмена мощности лазера S
            if args.laser and int(args.laser)<=100 and s:
                line = re.sub(r'S(\d+)', f'S{args.laser*10}', line)

            # Подмена скорости F
            if args.speed and F:
                line = re.sub(r'F(\d+)', f'F{args.speed}', line)
                
            l_block = re.sub(r'(\s)|(;.*)', '', line).upper()
            if not l_block:
                continue

            if verbose:
                print(f"SND> line {l_count}/{lines_in_file} : {l_block}", end='\r')

            ser.write(l_block.encode() + b'\n')

            while True:
                grbl_out = ser.readline().decode().strip()

                if grbl_out.lower().strip() == 'ok':
                    if verbose:
                        print(f"  REC< line {l_count}/{lines_in_file} : {grbl_out}", end='\r')
                    break

                elif 'error' in grbl_out.lower():
                    err_key = int(grbl_out.split(':')[1])
                    if err_key in grbl_errors.keys():
                        err_key = f'{err_key} {grbl_errors[err_key]}'
                    print(Fore.RED + f"\n  ERR< {l_count}/{lines_in_file} {l_block} : {err_key}" + Style.RESET_ALL)
                    errors_count += 1
                    if errors_count >= MAX_ERRORS:
                        print(Fore.RED + f'\n\n!!! Слишком много ошибок !!!\n\n' + Style.RESET_ALL)
                        exit()

                else: # --- MSG --- MSG --- MSG ---
                    my_out = f'    MSG:  {repeats_count}/{args.repeats} {l_count}/{lines_in_file} {int(l_count*100/lines_in_file)}% {pieces_cycle_count}/{pieces_count}'
                    report_out = f"{my_out} {grbl_out}"
                    clear_len = last_report_len - len(report_out)
                    print(f"{report_out}{' '*clear_len}", end='\r')
                    last_report_len = len(report_out)

                    if 'pos' in grbl_out.lower():
                        if beep_switch and (position_from_status(grbl_out)[1]>y_beep_position):
                            beep(1)
                            beep_switch = False
                # time.sleep(0.01)
    else:
        # Send g-code program via a more agressive streaming protocol that forces characters into
        # Grbl's serial read buffer to ensure Grbl has immediate access to the next g-code command
        # rather than wait for the call-response serial protocol to finish. This is done by careful
        # counting of the number of characters sent by the streamer to Grbl and tracking Grbl's
        # responses, such that we never overflow Grbl's serial read buffer.

        l_count = 0         # Lines file counter
        l_block_count = 0   # Lines with g-code counter
        g_count = 0         # Received responses counter
        c_line = []
        for line in file:
            l_count += 1 # Iterate line counter
            x, y, xy, F, s, sxy = data_from_gcode(line)

            # Сохранить начальную позию для следующего цикла
            if 'G0' in line.upper() and x and y:
                start_position = line

            # Звуковой сигнал, если надена метка ; beep
            if '; beep' in line.lower():
                beep(1)

            # Счётчики деталей
            if 'G1' in line.upper() and not s and y >= args.pieces_distance:
                pieces_count += 1
                pieces_cycle_count += 1
                if is_last_piece:
                    break

            # Статистика
            if 'G1' in line.upper() or 'G0' in line.upper():
                x_move_cycle_count += abs(x)
                y_move_cycle_count += abs(y)
                xy_move_cycle_count += xy
                s_cycle_count += sxy

            # Подмена мощности лазера S
            if args.laser and int(args.laser)<=100 and s:
                line = re.sub(r'S(\d+)', f'S{args.laser*10}', line)

            # Подмена скорости F
            if args.speed and F:
                line = re.sub(r'F(\d+)', f'F{args.speed}', line)

            l_block = re.sub(r'(\s)|(;.*)', '', line).upper()
            if not l_block:
                continue

            l_block_count += 1
            c_line.append(len(l_block)+1) # Track number of characters in grbl serial read buffer
            # print(f'{sum(c_line)} : {c_line} : {ser.inWaiting()}')    # Buffer debug

            while sum(c_line) >= RX_BUFFER_SIZE-1 or ser.inWaiting():
                out_temp = ser.readline().decode().strip()

                if out_temp.lower().strip() == 'ok':
                    g_count += 1 # Iterate g-code counter
                    del c_line[0] # Delete the block character count corresponding to the last 'ok'
                    if verbose:
                        print(f"  REC< line {l_count}/{lines_in_file} : {out_temp}", end='\r')

                elif 'error' in out_temp:
                    g_count += 1 # Iterate g-code counter
                    del c_line[0]
                    err_key = int(out_temp.split(':')[1])
                    if err_key in grbl_errors.keys():
                        err_key = f'{err_key} {grbl_errors[err_key]}'
                    print(Fore.RED + f"\n  ERR< {l_count}/{lines_in_file} {l_block} : {err_key}" + Style.RESET_ALL) # Debug response
                    errors_count += 1
                    if errors_count > MAX_ERRORS:
                        print(Fore.RED + f'\n\n!!! Слишком много ошибок !!!\n\n' + Style.RESET_ALL)
                        exit()

                else:
                    percents = round(l_count*100/lines_in_file)
                    # percents = int(l_count*100//lines_in_file + (l_count*100%lines_in_file/lines_in_file >= 0.5))
                    my_out = f'    MSG: {repeats_count}/{args.repeats} {l_count}/{lines_in_file} {percents}% {pieces_cycle_count}/{pieces_count}'
                    report_out = f"{my_out} {out_temp}"
                    clear_len = last_report_len - len(report_out)
                    print(f"{report_out}{' '*clear_len}", end='\r') # Clean last report out
                    last_report_len = len(report_out)
                    if is_last_cycle:
                        title = f"{repeats_count}/{repeats_count+1} {percents}% {pieces_cycle_count}/{pieces_count} *"
                    else:
                        title = f"{repeats_count}/{args.repeats} {percents}% {pieces_cycle_count}/{pieces_count}"
                    window.title(title)
                    if 'pos' in out_temp.lower():
                        if beep_switch and (position_from_status(out_temp)[1]>y_beep_position):
                            beep(1)
                            beep_switch = False

            if verbose:
                print(f"SND> {l_count}/{lines_in_file} : {l_block}", end='\r')

            ser.write(l_block.encode() + b'\n')

        # Wait until all responses have been received.
        while l_block_count > g_count:
            out_temp = ser.readline().decode().strip()
            # print(f'{sum(c_line)} : {c_line} : {ser.inWaiting()}')    # Buffer debug
            if out_temp.lower().strip() == 'ok':
                g_count += 1 # Iterate g-code counter
                del c_line[0] # Delete the block character count corresponding to the last 'ok'
                if verbose:
                    print(f"  REC< line {l_count}/{lines_in_file} : {out_temp}", end='\r')
            elif 'error' in out_temp:
                g_count += 1 # Iterate g-code counter
                del c_line[0]
                err_key = int(out_temp.split(':')[1])
                if err_key in grbl_errors.keys():
                    err_key = f'{err_key} {grbl_errors[err_key]}'
                print(Fore.RED + f"\n  ERR< {l_count}/{lines_in_file} : {err_key}" + Style.RESET_ALL) # Debug response
                errors_count += 1
            else:
                my_out = f'    MSG: {repeats_count}/{args.repeats} {l_count}/{lines_in_file} {int(l_count*100/lines_in_file)}% {pieces_cycle_count}/{pieces_count}'
                report_out = f"{my_out} {out_temp}"
                clear_len = last_report_len - len(report_out)
                print(f"{report_out}{' '*clear_len}", end='\r')
                last_report_len = len(report_out)

    repeats_count += 1
    seconds_elapsed_cycle = round(time.time() - start_time_cycle)
    seconds_elapsed_program = round(time.time() - start_time_program)
    pieces_count += 1
    pieces_cycle_count += 1
    # piece_average_time = round(seconds_elapsed_cycle / pieces_cycle_count)
    piece_average_time = seconds_elapsed_cycle//pieces_cycle_count + (seconds_elapsed_cycle%pieces_cycle_count > 0)
    average_power = s_cycle_count / xy_move_cycle_count

    add_stat(start_time_cycle, pieces_cycle_count, x_move_cycle_count, 2*y_move_cycle_count, average_power)
    
    date_start = time.strftime('%d-%m-%Y', time.localtime(start_time_program))
    date_finish = time.strftime('%d-%m-%Y', time.localtime())
    if date_start == date_finish:
        period = f"с {date_time(start_time_program).split()[0]} по {date_time()}"
    else:
        period = f"с {date_time(start_time_program)} по {date_time()}"

    print(Fore.GREEN + '\n')
    print(f"Файл Gcode:        {file.name}")
    print(f"Время работы:      {time.strftime('%H:%M:%S', time.gmtime(seconds_elapsed_program))} ({period})")
    print(f"Время цикла:       {seconds_elapsed_cycle} сек {time.strftime('%M:%S', time.localtime(seconds_elapsed_cycle))} ({piece_average_time} сек на деталь)")
    print(f"Завершено:         циклов - {repeats_count}, деталей - {pieces_count}")
    # print(f"Laser moves: {int(average_power/10)}%")
    print(f"\n" + Style.RESET_ALL)
    if errors_count:
        print(Fore.RED + f"!!! {errors_count} ошибок !!!\n" + Style.RESET_ALL)

    if args.home_cycles and not args.check and not is_last_cycle  \
    and not repeats_count%args.home_cycles:
        homing()
    else:
        ser.write(b'G90\n')
        ser.write(start_position.encode())
        check_ok = 0
        while 1:
            out_temp = ser.readline().decode().strip()
            if out_temp.lower().strip() == 'ok':
                check_ok += 1
            # print(f'--{out_temp}--', end='\r')
            if 'pos' in out_temp.lower() and check_ok == 2:
                if ('idle' in out_temp.lower()) or (position_from_status(out_temp)[1] < y_beep_position):
                    break

    # Завершение исполнения программы по запросу
    if is_last_cycle:
        break


# Закрыть файл и порт
is_run = False
file.close()
ser.close()

if is_last_cycle:
    print(Fore.YELLOW + f"Цикл завершён по запросу\n" + Style.RESET_ALL)
else:
    print(Fore.YELLOW + f'Работа завершена ({repeats_count}/{args.repeats})\n' + Style.RESET_ALL)
