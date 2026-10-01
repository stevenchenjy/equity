"""Bind only the signed-in owner's Tailscale identity to HTTPS Serve.

Run after the owner grants macOS extension/VPN permission and signs in. Does
not create credentials, expose Funnel, share a device or modify tailnet ACLs.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from feedback import atomic
from install_service import ROOT, LABEL

CLI='/Applications/Tailscale.app/Contents/MacOS/Tailscale'


def command(*args):
    return subprocess.run([CLI,*args],capture_output=True,text=True,timeout=15,check=True).stdout


def our_route(config,host):
    """Allow a retry only when every existing route belongs to this app."""
    return (config.get('TCP')=={'443':{'HTTPS':True}}
            and config.get('Web')=={host+':443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8765'}}}})


def main():
    if Path(__file__).resolve().parent != ROOT/'10_dashboard': raise SystemExit('Use the verified production checkout.')
    try: state=json.loads(command('status','--json'))
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError,ValueError):
        raise SystemExit('Tailscale is not ready. Complete the Mac app permissions and login first.')
    if state.get('BackendState')!='Running': raise SystemExit('Tailscale is not signed in and connected. Complete the Mac app onboarding first.')
    me=state['Self']; host=me['DNSName'].rstrip('.')
    owner=state['User'][str(me['UserID'])]['LoginName']
    if not host.endswith('.ts.net') or not owner: raise SystemExit('An owner identity and MagicDNS HTTPS name are required.')
    existing=json.loads(command('serve','status','--json'))
    if existing.get('AllowFunnel') and any(existing['AllowFunnel'].values()): raise SystemExit('Existing Funnel configuration needs owner review; private setup stopped.')
    if (existing.get('Web') or existing.get('TCP')) and not our_route(existing,host):
        raise SystemExit('A different Tailscale service already exists. Review its routes before configuring this dashboard.')
    atomic(ROOT,'07_automation/dashboard.local/access.json',(json.dumps({'host':host,'owner_login':owner},indent=2)+'\n').encode())
    subprocess.run(['/bin/launchctl','kickstart','-k','gui/'+str(os.getuid())+'/'+LABEL],check=True)
    # The CLI may require the owner to enable HTTPS through a consent URL.
    try: command('serve','--bg','--https=443','http://127.0.0.1:8765')
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout); raise SystemExit('Complete the Tailscale HTTPS consent, then run this command again.')
    configured=json.loads(command('serve','status','--json'))
    if any(configured.get('AllowFunnel',{}).values()) or not our_route(configured,host): raise SystemExit('Private-only route verification failed.')
    print('Private owner-only dashboard: https://'+host)


if __name__=='__main__': main()
