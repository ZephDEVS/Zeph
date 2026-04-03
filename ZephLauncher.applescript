set appPath to POSIX path of (path to me)
set repoDir to do shell script "dirname " & quoted form of appPath
do shell script "cd " & quoted form of repoDir & " && nohup ./.venv/bin/python -m daia.main --gui >/tmp/zeph-gui.log 2>&1 &"
