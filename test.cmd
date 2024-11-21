@echo off

: ���� � ����� gcode
set gcode="d:\laser\test.gcode"

: �������� ������ %
set /a laser=80

: �������� ��/���
set /a speed=20000

: ���������� ��������
set /a repeats=99

: ���������� ����� ��������
set /a pieces_distance=10

: ������ ��� ���������� ���������� Y
set /a y_beep=520                             

: ���� (COM3-Bluetooth, COM9-USB)
set port=COM3

: ���� � �������� python
set script=d:\laser\software\python\stream.py

python %script% -p %port% --home -r %repeats% -d %pieces_distance% -y %y_beep% -l %laser% -f %speed% %gcode%

pause
