"""Explicit integration check; install ReclaimLab 1.x and DevPocket 1.x first."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from reclaimlab.demo import synthetic, write_study
from reclaimlab.trace import exclusive, write_row
from reclaimlab import bundle, har, network_study


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
        assert any(x['name']=='reclaimlab-har' and not x['enabled'] for x in inventory)
        assert any(x['name']=='reclaimlab-network-study' and not x['enabled'] for x in inventory)
        assert any(x['name']=='reclaimlab-bundle' and not x['enabled'] for x in inventory)
        assert any(x['name']=='reclaimlab-har-compare' and not x['enabled'] for x in inventory)
        command(['plugins','enable','reclaimlab'],root)
        command(['plugins','enable','reclaimlab-study'],root)
        command(['plugins','enable','reclaimlab-har'],root)
        command(['plugins','enable','reclaimlab-network-study'],root)
        command(['plugins','enable','reclaimlab-bundle'],root)
        command(['plugins','enable','reclaimlab-har-compare'],root)
        capture = har.synthetic()
        (root / 'demo.har').write_text(json.dumps(capture))
        (root / 'after.har').write_text(json.dumps(capture))
        compare_input = {'before': 'demo.har', 'after': 'after.har'}
        comparison = json.loads(command(['run', 'reclaimlab-har-compare', '--input', json.dumps(compare_input), '--format', 'json'], root))
        assert comparison['data']['delta']['body_bytes']['change'] == 0
        assert 'example.invalid' not in json.dumps(comparison)
        har_input = {'capture': 'demo.har', 'max_errors': 0}
        network = json.loads(command(['run', 'reclaimlab-har', '--input', json.dumps(har_input), '--format', 'json'], root, expected=1))
        assert network['data']['verdict'] == 'budget exceeded'
        assert network['data']['summary']['requests'] == 7
        assert 'requests' not in network['data']
        assert 'example.invalid' not in json.dumps(network)
        sarif = json.loads(command(['run', 'reclaimlab-har', '--input', json.dumps(har_input), '--format', 'sarif'], root, expected=1))
        assert any(f['ruleId'].endswith('har-budget-errors') for f in sarif['runs'][0]['results'])
        (root / 'dist').mkdir()
        (root / 'dist' / 'index.html').write_text('<script src="app.js"></script>')
        (root / 'dist' / 'app.js').write_text('console.log("fixture");')
        build = json.loads(command(['run', 'assetguard', '--input', '{"path":"dist","max_total_gzip_kib":16}', '--format', 'json'], root))
        assert build['data']['summary']['files'] == 2
        report=json.loads(command(['run','reclaimlab','--input','{"trace":"demo.jsonl"}','--format','json'],root,expected=1))
        assert len(report['findings'])>=3
        manifest = write_study(root / 'trial')
        study_input = {'manifest': 'trial/study.json', 'iterations': 500}
        result = json.loads(command(['run', 'reclaimlab-study', '--input', json.dumps(study_input), '--format', 'json'], root))
        assert result['data']['verdict'] == 'consistent lower measured wake delay'
        assert any(f['rule'] == 'study-synthetic' for f in result['findings'])
        network_manifest = network_study.write_demo(root / 'network-trial')
        paired_input = {'manifest': 'network-trial/network-study.json', 'iterations': 500, 'max_growth': 0}
        paired = json.loads(command(['run', 'reclaimlab-network-study', '--input', json.dumps(paired_input), '--format', 'json'], root))
        assert paired['data']['gate']['state'] == 'pass'
        assert paired['data']['valid_pairs'] == 6
        assert 'example.invalid' not in json.dumps(paired)
        bundle.create(network_manifest, root / 'experiment.rlb', iterations=500, max_growth=0)
        bundle_input = {'bundle': 'experiment.rlb', 'max_growth': 0}
        portable = json.loads(command(['run', 'reclaimlab-bundle', '--input', json.dumps(bundle_input), '--format', 'json'], root))
        assert portable['data']['bundle']['integrity'] == 'verified'
        config = {'version': 1, 'plugins': ['reclaimlab', 'reclaimlab-study', 'reclaimlab-har', 'reclaimlab-network-study'], 'checks': {'trace': {'tool': 'reclaimlab', 'input': {'trace': 'demo.jsonl'}, 'cache': {'inputs': ['demo.jsonl']}}, 'study': {'tool': 'reclaimlab-study', 'input': study_input, 'cache': {'inputs': ['trial']}}, 'network': {'tool': 'reclaimlab-har', 'input': har_input, 'cache': {'inputs': ['demo.har']}}, 'paired-network': {'tool': 'reclaimlab-network-study', 'input': paired_input, 'cache': {'inputs': ['network-trial']}}}}
        (root / '.devpocket.json').write_text(json.dumps(config))
        config['plugins'].append('reclaimlab-bundle')
        config['checks']['bundle'] = {'tool': 'reclaimlab-bundle', 'input': bundle_input, 'cache': {'inputs': ['experiment.rlb']}}
        config['plugins'].append('reclaimlab-har-compare')
        config['checks']['comparison'] = {'tool': 'reclaimlab-har-compare', 'input': compare_input, 'cache': {'inputs': ['demo.har', 'after.har']}}
        (root / '.devpocket.json').write_text(json.dumps(config))
        preflight = json.loads(command(['config', 'validate', '--format', 'json'], root))
        assert preflight['data']['plugin_inputs_unverified'] == 6
        # Reuse assertions are serialized; parallel execution is exercised below.
        # Storage contention may safely bypass an optional cache on Windows.
        first = json.loads(command(['check', '--jobs', '1', '--format', 'json'], root, expected=1))
        reused = json.loads(command(['check', '--jobs', '1', '--format', 'json'], root, expected=1))
        cache_states = lambda report: {s['name']: s['report'].get('cache') for s in report['checks']}
        assert all(s['report']['cache']['status'] == 'miss' for s in first['checks']), cache_states(first)
        assert all(s['report']['cache']['status'] == 'hit' for s in reused['checks']), cache_states(reused)
        capture['log']['entries'][-1]['response']['status'] = 200
        (root / 'demo.har').write_text(json.dumps(capture))
        updated = json.loads(command(['check', '--jobs', '1', '--format', 'json'], root, expected=1))
        network = next(s for s in updated['checks'] if s['name'] == 'network')['report']
        assert network['cache']['status'] == 'miss'
        assert network['data']['verdict'] == 'within budgets'
        comparison = next(s['report'] for s in updated['checks'] if s['name'] == 'comparison')
        assert comparison['cache']['status'] == 'miss'
        assert comparison['data']['delta']['errors']['change'] == 1
        capture['log']['entries'][0]['response']['bodySize'] += 100
        (root / 'after.har').write_text(json.dumps(capture))
        changed_after = json.loads(command(['check', '--jobs', '1', '--format', 'json'], root, expected=1))
        comparison = next(s['report'] for s in changed_after['checks'] if s['name'] == 'comparison')
        assert comparison['cache']['status'] == 'miss'
        assert comparison['data']['delta']['body_bytes']['change'] == 100
        comparison_sarif = json.loads(command(['run', 'reclaimlab-har-compare', '--input', json.dumps(compare_input), '--format', 'sarif'], root))
        assert any(f['ruleId'].endswith('har-comparison-descriptive') for f in comparison_sarif['runs'][0]['results'])
        selected = next((manifest.parent / 'captures').glob('*-candidate.jsonl'))
        original = selected.read_text()
        selected.write_text(original.replace('synthetic repeated workload', 'different workload'))
        changed = json.loads(command(['check', '--jobs', '1', '--format', 'json'], root, expected=1))
        changed_study = next(s for s in changed['checks'] if s['name'] == 'study')['report']
        assert changed_study['cache']['status'] == 'miss'
        assert changed_study['data']['verdict'] == 'not comparable'
        selected.write_text(original)
        bundle.create(network_manifest, root / 'updated.rlb', iterations=600, max_growth=0)
        (root / 'experiment.rlb').write_bytes((root / 'updated.rlb').read_bytes())
        changed_bundle = json.loads(command(['check', '--jobs', '1', '--format', 'json'], root, expected=1))
        portable = next(s['report'] for s in changed_bundle['checks'] if s['name'] == 'bundle')
        assert portable['cache']['status'] == 'miss'
        assert portable['data']['bundle']['integrity'] == 'verified'
        workspace = {'version': 1, 'projects': {'build': {'path': 'dist'}, 'browser': {'path': 'network-trial', 'needs': ['build']}}}
        (root / '.devpocket-workspace.json').write_text(json.dumps(workspace))
        (root / 'dist/.devpocket.json').write_text(json.dumps({'version': 1, 'checks': {'assets': {'tool': 'assetguard', 'input': {'path': '.', 'max_total_gzip_kib': 16}}}}))
        (root / 'network-trial/.devpocket.json').write_text(json.dumps({'version': 1, 'plugins': ['reclaimlab-network-study'], 'checks': {'experiment': {'tool': 'reclaimlab-network-study', 'input': {**paired_input, 'manifest': 'network-study.json'}, 'cache': {'inputs': ['network-study.json', 'captures']}}}}))
        plan = json.loads(command(['workspace', 'plan', '--format', 'json'], root))['data']
        assert plan['levels'] == [['build/assets'], ['browser/experiment']]
        combined = json.loads(command(['workspace', 'check', '--expect-plan', plan['plan_sha256'], '--format', 'json'], root))
        assert [s['status'] for s in combined['checks']] == ['passed', 'passed']
        combined_sarif = json.loads(command(['workspace', 'check', '--format', 'sarif'], root))
        assert combined_sarif['runs'][0]['invocations'][0]['properties']['selectedProjects'] == ['build', 'browser']
        assert any(f['properties']['project'] == 'browser' for f in combined_sarif['runs'][0]['results'])
        paired_capture = next((network_manifest.parent / 'captures').glob('*-candidate.har'))
        saved = paired_capture.read_text()
        broken = json.loads(saved)
        broken['log']['entries'][0]['timings']['wait'] = -1
        paired_capture.write_text(json.dumps(broken))
        invalidated = json.loads(command(['workspace', 'check', '--format', 'json', '--fail-on', 'none'], root, expected=1))
        assert invalidated['checks'][1]['report']['cache']['status'] == 'miss'
        assert invalidated['checks'][1]['report']['data']['gate']['state'] == 'unknown'
        paired_capture.write_text(saved)
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'reclaimlab-test','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'reclaimlab','arguments':{'trace':'demo.jsonl'}}},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'reclaimlab-study','arguments':study_input}},{'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'reclaimlab-har','arguments':har_input}},{'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'reclaimlab-network-study','arguments':paired_input}},{'jsonrpc':'2.0','id':6,'method':'tools/call','params':{'name':'reclaimlab-bundle','arguments':bundle_input}}]
        messages.append({'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': 'reclaimlab-har-compare', 'arguments': compare_input}})
        result=command(['serve','--root',root,'--plugin','reclaimlab','--plugin','reclaimlab-study','--plugin','reclaimlab-har','--plugin','reclaimlab-network-study','--plugin','reclaimlab-bundle','--plugin','reclaimlab-har-compare'],root,input=''.join(json.dumps(x)+'\n' for x in messages))
        replies={x['id']:x for x in map(json.loads,result.splitlines())}
        assert not replies[2]['result']['isError']
        assert len(replies[2]['result']['structuredContent']['findings'])>=3
        assert not replies[3]['result']['isError']
        assert replies[3]['result']['structuredContent']['data']['valid_pairs'] == 6
        assert not replies[4]['result']['isError']
        assert replies[4]['result']['structuredContent']['data']['summary']['requests'] == 7
        assert not replies[5]['result']['isError']
        assert replies[5]['result']['structuredContent']['data']['gate']['state'] == 'pass'
        assert not replies[6]['result']['isError']
        assert replies[6]['result']['structuredContent']['data']['bundle']['integrity'] == 'verified'
        assert not replies[7]['result']['isError']
        assert replies[7]['result']['structuredContent']['data']['delta']['body_bytes']['change'] == 100
        print('DevPocket six-plugin discovery, AssetGuard, HAR comparison, paired gates, cached checks, both-input invalidation, workspace plans/SARIF and MCP integration passed.')
    return 0

if __name__=='__main__':raise SystemExit(main())
