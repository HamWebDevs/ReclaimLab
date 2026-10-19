"""Optional real-browser QA. Install Playwright and its Chromium browser first."""
import argparse
from pathlib import Path

from reclaimlab import har, network_study
from reclaimlab.report import create_network, create_network_study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-directory', required=True, help='Fresh directory for the synthetic report and screenshots')
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    output = Path(args.output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = output / 'network.html'
    create_network(har.analyse(har.synthetic(), include_paths=True), report)
    manifest = network_study.write_demo(output / 'study')
    study_report = output / 'network-study.html'
    create_network_study(network_study.evaluate(manifest, iterations=500, max_growth=0), study_report)
    errors, network = [], []
    with sync_playwright() as automation:
        browser = automation.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1080}, device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: network.append(request.url) if not request.url.startswith('file:') else None)
        page.goto(report.as_uri())
        page.wait_for_selector('#request-rows button')
        assert page.locator('#request-rows tr').count() == 7
        assert page.locator('#stat-requests').inner_text() == '7'
        page.get_by_label('Errors only').check()
        assert page.locator('#request-rows tr').count() == 1
        assert page.locator('#request-rows').inner_text().count('503') == 1
        page.get_by_label('Errors only').uncheck()
        page.get_by_label('Resource', exact=True).select_option('script')
        assert page.locator('#request-rows tr').count() == 1
        page.get_by_label('Resource', exact=True).select_option('all')
        page.get_by_label('Find a request', exact=True).fill('/api/feed')
        assert page.locator('#request-rows tr').count() == 2
        assert page.locator('#stat-requests').inner_text() == '7'
        page.get_by_label('Find a request', exact=True).fill('')
        page.locator('#time-start').fill('800')
        page.locator('#time-end').fill('900')
        assert page.locator('#request-rows tr').count() == 2
        page.get_by_role('button', name='Full capture', exact=True).click()
        assert page.locator('#request-rows tr').count() == 7
        for width, name in ((1440, 'desktop'), (390, 'mobile')):
            page.set_viewport_size({'width': width, 'height': 900})
            fits = page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert fits, 'Page overflows its viewport at ' + name
            page.screenshot(path=str(output / ('network-' + name + '.png')), full_page=True)
        assert not errors, errors
        assert not network, network
        page.goto(study_report.as_uri())
        page.wait_for_selector('#pair-rows button')
        assert page.locator('#pair-rows tr').count() == 6
        assert page.locator('#pairs').inner_text() == '6 / 6'
        assert page.locator('#gate').inner_text() == 'Growth gate: pass'
        assert page.locator('#synthetic').is_visible()
        page.get_by_label('Capture order', exact=True).select_option('baseline')
        assert page.locator('#pair-rows tr').count() == 3
        assert page.locator('#pairs').inner_text() == '6 / 6'
        page.locator('#pair-rows button').first.click()
        assert page.locator('#detail').is_visible()
        assert 'summary' in page.locator('#detail-data').inner_text()
        page.get_by_label('Incompatible only', exact=True).check()
        assert page.locator('#pair-rows tr').count() == 0
        page.get_by_role('button', name='Reset filters', exact=True).click()
        page.get_by_label('Sort pairs', exact=True).select_option('delta')
        assert page.locator('#pair-rows tr').count() == 6
        for width, name in ((1440, 'desktop'), (390, 'mobile')):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), name
            page.screenshot(path=str(output / ('network-study-' + name + '.png')), full_page=True)
        assert not errors, errors
        assert not network, network
        browser.close()
    print('Real Chromium network + paired-experiment QA passed: desktop/mobile layout, filters, audit details, stable totals, no JavaScript errors or network requests.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
