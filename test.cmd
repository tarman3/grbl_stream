@echo off

: Путь к файлу gcode
set gcode="d:\laser\test.gcode"

: Мощность лазера %
set /a laser=80

: Скорость мм/мин
set /a speed=20000

: Количество повторов
set /a repeats=99

: Расстояние между деталями
set /a pieces_distance=10

: Сигнал при превышении координаты Y
set /a y_beep=520                             

: Порт (COM3-Bluetooth, COM9-USB)
set port=COM3

: Путь к сценарию python
set script=d:\laser\software\python\stream.py

python %script% -p %port% --home -r %repeats% -d %pieces_distance% -y %y_beep% -l %laser% -f %speed% %gcode%

pause
