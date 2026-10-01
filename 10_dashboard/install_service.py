"""Install/restart the loopback production dashboard as a user LaunchAgent."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT=Path('/Users/messssi/LocalRuntime/equity')
LABEL='com.steven.equity_research.dashboard'


def main():
    if Path(__file__).resolve().parent != ROOT/'10_dashboard':
        raise SystemExit('Install from the verified production checkout after sync.')
    log=ROOT/'07_automation/dashboard.local'; log.mkdir(parents=True,exist_ok=True,mode=0o700);log.chmod(0o700)
    agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
    target=agents/(LABEL+'.plist')
    config=dict(Label=LABEL,ProgramArguments=[sys.executable,str(ROOT/'10_dashboard/server.py'),'--runtime-root',str(ROOT),'--port','8765'],
                WorkingDirectory=str(ROOT/'10_dashboard'),RunAtLoad=True,KeepAlive=True,ThrottleInterval=10,
                StandardOutPath=str(log/'server.log'),StandardErrorPath=str(log/'server-error.log'),
                EnvironmentVariables={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','PYTHONUNBUFFERED':'1'},Umask=0o077)
    domain='gui/'+str(os.getuid())
    subprocess.run(['/bin/launchctl','bootout',domain+'/'+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    target.write_bytes(plistlib.dumps(config));target.chmod(0o600)
    subprocess.run(['/bin/launchctl','bootstrap',domain,str(target)],check=True)
    print('Dashboard LaunchAgent installed; loopback only. Verify /api/snapshot and runtime HEAD.')


if __name__=='__main__': main()
