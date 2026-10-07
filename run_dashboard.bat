@echo off
cd /d "%~dp0"
rem Use Anaconda Python even if it is not on PATH (no conda activate needed)
set "PY_HOME="
if exist "%USERPROFILE%\anaconda3\python.exe" set "PY_HOME=%USERPROFILE%\anaconda3"
if not defined PY_HOME if exist "%USERPROFILE%\miniconda3\python.exe" set "PY_HOME=%USERPROFILE%\miniconda3"
if not defined PY_HOME if exist "%ProgramData%\anaconda3\python.exe" set "PY_HOME=%ProgramData%\anaconda3"
if not defined PY_HOME if exist "%LOCALAPPDATA%\anaconda3\python.exe" set "PY_HOME=%LOCALAPPDATA%\anaconda3"
if not defined PY_HOME goto run
set "PATH=%PY_HOME%;%PY_HOME%\Library\mingw-w64\bin;%PY_HOME%\Library\usr\bin;%PY_HOME%\Library\bin;%PY_HOME%\Scripts;%PATH%"
:run
where python
python -m streamlit run app.py
pause
