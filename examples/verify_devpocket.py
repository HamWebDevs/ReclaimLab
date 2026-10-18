"""Explicit integration check; install ReclaimLab and DevPocket 0.3 first."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from reclaimlab.demo import synthetic
from reclaimlab.trace import exclusive, write_row


def command(args, cwd, expected=0, input=None):
    result=subprocess.run([sys.executable,'-m','devpocket',*map(str,args)],cwd=cwd,input=input,text=True,capture_output=True,timeout=30)
    if result.returncode!=expected:
        raise AssertionError(result.stdout+'\n'+result.stderr)
    return result.stdout


def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory).resolve()
        trace=synthetic()
        with exclusive(root/'demo.jsonl') as stream:
            for row in [trace['header'],*trace['samples'],*trace['markers'],trace['footer']]:write_row(stream,row)
        inventory=json.loads(command(['plugins','list','--json'],root))
        assert any(x['name']=='reclaimlab' and not x['enabled'] for x in inventory)
        command(['plugins','enable','reclaimlab'],root)
        report=json.loads(command(['run','reclaimlab','--input','{"trace":"demo.jsonl"}','--format','json'],root,expected=1))
        assert len(report['findings'])>=3
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'reclaimlab-test','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'reclaimlab','arguments':{'trace':'demo.jsonl'}}}]
        result=command(['serve','--root',root,'--plugin','reclaimlab'],root,input=''.join(json.dumps(x)+'\n' for x in messages))
        replies={x['id']:x for x in map(json.loads,result.splitlines())}
        assert not replies[2]['result']['isError']
        assert len(replies[2]['result']['structuredContent']['findings'])>=3
        print('DevPocket plugin discovery, enablement, structured findings and MCP integration passed.')
    return 0

if __name__=='__main__':raise SystemExit(main())
