import zipfile, json

pbix = 'powerbi/mf_analytics_dashboard.pbix'
with zipfile.ZipFile(pbix, 'r') as z:
    page1_prefix = 'Report/definition/pages/b5a4a9ec836108a694af/visuals/'
    visuals = [f for f in z.namelist() if f.startswith(page1_prefix) and f.endswith('visual.json')]

    for v in visuals:
        d = json.loads(z.read(v))
        vtype = d.get('visual', {}).get('visualType', '?')
        if vtype in ('scatterChart', 'pivotTable', 'slicer', 'clusteredBarChart', 'barChart'):
            print(f"\n{'='*60}")
            print(f"TYPE: {vtype} — {v.split('/')[4]}")
            print(json.dumps(d, indent=2)[:6000])

    # Also read page 2
    page2_prefix = 'Report/definition/pages/1f14492bb3a11526ba5f/'
    print('\n\n=== PAGE 2 page.json ===')
    print(json.dumps(json.loads(z.read(page2_prefix + 'page.json')), indent=2))
