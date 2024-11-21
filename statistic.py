import time
import re
import argparse
from colorama import init, Fore, Style
init()

min_time = 30 # Минимальное время обработки одной детали
              # При меньшей длительности считать выполненным в режиме симуляции (check) и пропускать


def date_time(unix_time=time.time()):
    t = time.localtime(unix_time)
    c_time = time.strftime("%H:%M:%S %d-%m-%Y", t)
    return c_time

def show_global_stat(file):
    stat_time = 0
    stat_pieces = 0
    stat_move_x = 0
    stat_move_y = 0
    stat_power = 0
    for line in file:
        data = re.split('\s+', line.strip())
        if len(data) > 6:
            stat_time += int(data[1]) - int(data[0]) # sec
            stat_pieces += int(data[3])
            stat_move_x += int(data[4]) # mm
            stat_move_y += int(data[5]) # mm
            # stat_power += int(data[6]) * (int(data[4])**2 + int(data[5])**2) **0.5 # by x,y moves
            stat_power += int(data[6]) * (int(data[1]) - int(data[0])) # by time
    # stat_power = int(stat_power / ((stat_move_x**2 + stat_move_y**2) **0.5))
    stat_power = int(stat_power / stat_time)
    print(Fore.YELLOW + f"\n-------- ОБЩАЯ СТАТИСТИКА --------\n")
    print(f"Время работы:          {int(stat_time/(1*60*60))} ч")
    print(f"Деталей обработано:    {stat_pieces} шт")
    print(f"Перемещения оси X:     {int(stat_move_x/1000)} м")
    print(f"Перемещения оси Y:     {int(stat_move_y/1000)} м")
    print(f"Перемещений с лазером: {int(stat_power/10)} %")
    print(f"" + Style.RESET_ALL)

def show_days_stat(file):
    print(f"\n------- СТАТИСТИКА ПО ДНЯМ -------\n")
    pieces_counter_dict = {}
    date_last = ''
    line_counter = 1
    file.seek(0)
    for line in file:
        data = re.split('\s+', line.strip())
        if len(data) > 6 and ((int(data[1])-int(data[0]))/int(data[3]) > min_time):
            key = f'{data[7]} {data[2]}' if len(data)>7 else f'--- {data[2]}'
            t = time.localtime(int(data[0]))
            date = time.strftime("%Y-%m-%d", t)      
            if date == date_last:
                if key in pieces_counter_dict.keys():
                    pieces_counter_dict[key] += int(data[3])
                else:
                    pieces_counter_dict[key] = int(data[3])       
            else:
                if len(pieces_counter_dict):
                    print(f'{date_last}  {pieces_counter_dict}')               
                pieces_counter_dict = {}
                pieces_counter_dict[key] = int(data[3])
        # Вывод тестовых записей с малой длительностью
        # if len(data) <= 6 or ((int(data[1])-int(data[0]))/int(data[3]) <= min_time):
            # print(f'line={line_counter} - time={int(data[1])-int(data[0])} - {line}') 
        date_last = date
        line_counter += 1
    print(f'{date_last}  {pieces_counter_dict}\n')

parser = argparse.ArgumentParser(description='Statistic')
parser.add_argument('file', type=argparse.FileType('r'), help='statistic file')
args = parser.parse_args()
file = args.file

show_global_stat(file)
show_days_stat(file)
print(Fore.GREEN + f'Время формирования отчёта {date_time()}\n' + Style.RESET_ALL)

