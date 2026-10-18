"""Explicit integration check; install ReclaimLab 0.2 and DevPocket 0.4 first."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from reclaimlab.demo import synthetic, write_study
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
        assert any(x['name']=='reclaimlab-study' and not x['enabled'] for x in inventory)
        command(['plugins','enable','reclaimlab'],root)
        command(['plugins','enable','reclaimlab-study'],root)
        report=json.loads(command(['run','reclaimlab','--input','{"trace":"demo.jsonl"}','--format','json'],root,expected=1))
        assert len(report['findings'])>=3
        manifest = write_study(root / 'trial')
        study_input = {'manifest': 'trial/study.json', 'iterations': 500}
        result = json.loads(command(['run', 'reclaimlab-study', '--input', json.dumps(study_input), '--format', 'json'], root))
        assert result['data']['verdict'] == 'consistent lower measured wake delay'
        assert any(f['rule'] == 'study-synthetic' for f in result['findings'])
        config = {'version': 1, 'plugins': ['reclaimlab', 'reclaimlab-study'], 'checks': {'trace': {'tool': 'reclaimlab', 'input': {'trace': 'demo.jsonl'}, 'cache': {'inputs': ['demo.jsonl']}}, 'study': {'tool': 'reclaimlab-study', 'input': study_input, 'cache': {'inputs': ['trial']}}}}
        (root / '.devpocket.json').write_text(json.dumps(config))
        first = json.loads(command(['check', '--format', 'json'], root, expected=1))
        reused = json.loads(command(['check', '--format', 'json'], root, expected=1))
        assert all(s['report']['cache']['status'] == 'miss' for s in first['checks'])
        assert all(s['report']['cache']['status'] == 'hit' for s in reused['checks'])
        selected = next((manifest.parent / 'captures').glob('*-candidate.jsonl'))
        original = selected.read_text()
        selected.write_text(original.replace('synthetic repeated workload', 'different workload'))
        changed = json.loads(command(['check', '--format', 'json'], root, expected=1))
        changed_study = next(s for s in changed['checks'] if s['name'] == 'study')['report']
        assert changed_study['cache']['status'] == 'miss'
        assert changed_study['data']['verdict'] == 'not comparable'
        selected.write_text(original)
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'reclaimlab-test','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'reclaimlab','arguments':{'trace':'demo.jsonl'}}},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'reclaimlab-study','arguments':study_input}}]
        result=command(['serve','--root',root,'--plugin','reclaimlab','--plugin','reclaimlab-study'],root,input=''.join(json.dumps(x)+'\n' for x in messages))
        replies={x['id']:x for x in map(json.loads,result.splitlines())}
        assert not replies[2]['result']['isError']
        assert len(replies[2]['result']['structuredContent']['findings'])>=3
        assert not replies[3]['result']['isError']
        assert replies[3]['result']['structuredContent']['data']['valid_pairs'] == 6
        print('DevPocket trace/study discovery, enablement, cached checks, content invalidation and MCP integration passed.')
    return 0

if __name__=='__main__':raise SystemExit(main())
