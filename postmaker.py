# Creates full pages about an FZ project given its URL
# This allows me to demo and refine the output
import urllib.request
from scraper import scrape_single_project
from fritzing_parser import load_core_parts, parse_sketch
from describer import describe_as_html

TEMPLATE = '''
<p>
This page was generated from an open-source design by {proj.creator}.
You can <a href="{proj.url}">find the original project here</a>, 
and <a href="{proj.license_url}">read the license here</a>.
</p>

<h1>{proj.title}</h1>

<p><strong>{proj.tagline}</strong></p>

{proj.description_html}

{circuit_desc}
'''

TMP_FILE = '/tmp/scraped.fzz'

def project_to_md(url: str) -> str:
    proj = scrape_single_project(url)

    first_fzz_url = next((url for name, url in proj.download_urls.items() if name.lower().endswith('.fzz')))

    urllib.request.urlretrieve(first_fzz_url, TMP_FILE)

    # TODO this will redo a lot of work add some memoization or something
    parts_bin = load_core_parts()
    schematic = parse_sketch(parts_bin, TMP_FILE)

    circuit_desc = describe_as_html(schematic) 

    # TODO use Jinja for this it's not very safe.
    return TEMPLATE.format(proj=proj, circuit_desc=circuit_desc)


#url = 'https://fritzing.org/projects/breadboard-wee-blinky'
url = 'https://fritzing.org/projects/pwm-speed-controller'
url = 'https://fritzing.org/projects/metal-detector'
url = 'https://fritzing.org/projects/atari-punk-console-with-cv-inpus'
url = 'https://fritzing.org/projects/fritzing-amplifier'
url = 'https://fritzing.org/projects/chaos-circuit'

print(project_to_md(url))
