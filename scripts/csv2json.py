#!/usr/bin/env python3
"""Turn a directory of benchmark CSVs into the per-GPU JSON the leaderboard reads.

The benchmark harness writes one CSV per (dataset, index, reordering) run:

    <dataset>_gpu_<index>_K32_<dataset>_<metric>[_reordered_<reordering>]_itopk_size.csv
    param_value,recall@10,qps,wall_time_ms,total_ms

`src/components/leaderboard.jsx` instead wants one JSON per dataset, plus an
index.json listing them, under `src/data/<gpu>/json/`. Every reordered point
also carries how much faster it is than the un-reordered run at the same recall.

    python3 scripts/csv2json.py 6000ada/abacus-cagra-nsg-diskann rtx6000ada
"""

import argparse
import json
import re
import sys
from pathlib import Path

# The datasets the paper reports, in the order the A100 index.json lists them,
# with the paper's own display names. The harness also emits synthetic
# random1m-* runs; those are not part of the leaderboard.
DATASETS = {
    'wikipedia10m-768-ip': 'Wikipedia 10M',
    'wikipedia1m-768-ip': 'Wikipedia 1M',
    'sift-128-euclidean': 'SIFT 1M',
    'deep40m-96-euclidean': 'Deep 40M',
    'bioasq1m-1024-ip': 'BioASQ 1M',
    'bioasq10m-1024-ip': 'BioASQ 10M',
    'c45m-1536-ip': 'C4 5M',
    'openai1m-1536-euclidean': 'OpenAI Embed. 1M',
    'deep10m': 'Deep 10M',
    'deep1m-96-euclidean': 'Deep 1M',
    'gist-960-euclidean': 'GIST 1M',
    't2i1m-200-ip': 'Yandex T2I 1M',
}

# The three graph indices the charts plot. The harness also runs nndescent and
# nssg, which the leaderboard does not show.
INDICES = ['cagra', 'diskann', 'nsg']

REORDERINGS = ['none', 'gorder', 'hubsort', 'indegree', 'outdegree', 'random', 'rcm']

# A reordered point is compared against the baseline point closest in recall;
# further apart than this and the two are not measuring the same operating
# point, so the speedup is left unknown rather than guessed.
RECALL_TOLERANCE = 0.01

FILENAME = re.compile(
    r'^(?P<dataset>.+?)_gpu_(?P<index>[a-z]+)_K(?P<k>\d+)_(?P=dataset)_[a-z0-9]+'
    r'(?:_reordered_(?P<reordering>[a-z]+))?_itopk_size\.csv$'
)


def dump(data):
    """json.dumps at indent=2, but keeping a lone string on one line as Prettier does."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    return re.sub(r'\[\n\s+("[^"]*")\n\s+\]', r'[\1]', text) + '\n'


def read_csv(path):
    """(recall, qps) per row, skipping the header."""
    points = []
    for line in path.read_text().strip().splitlines()[1:]:
        _, recall, qps, *_ = line.split(',')
        points.append((float(recall), float(qps)))
    return points


def collect(src, k):
    """{dataset: {(index, reordering): [(recall, qps), ...]}} for the wanted runs."""
    runs = {}
    for path in sorted(src.iterdir()):
        m = FILENAME.match(path.name) if path.is_file() else None
        if not m or m['k'] != k:
            continue
        dataset, index = m['dataset'], m['index']
        reordering = m['reordering'] or 'none'
        if dataset not in DATASETS or index not in INDICES:
            continue
        if reordering not in REORDERINGS:
            continue
        runs.setdefault(dataset, {})[(index, reordering)] = read_csv(path)
    return runs


def closest_baseline(baseline, recall):
    if not baseline:
        return None
    point = min(baseline, key=lambda p: abs(p[0] - recall))
    return point if abs(point[0] - recall) <= RECALL_TOLERANCE else None


def build_dataset(dataset, runs):
    results = []
    for index in INDICES:
        baseline = runs.get((index, 'none'), [])
        for reordering in REORDERINGS:
            for recall, qps in runs.get((index, reordering), []):
                row = {
                    'dataset': dataset,
                    'index': index,
                    'reordering': reordering,
                    'qps': qps,
                    'recall': recall,
                }
                if reordering == 'none':
                    row['speedup_percent'] = 0.0
                else:
                    match = closest_baseline(baseline, recall)
                    row['speedup_percent'] = (
                        round((qps - match[1]) / match[1] * 100, 2) if match else None
                    )
                    row['baseline_qps'] = match[1] if match else None
                    row['baseline_recall'] = match[0] if match else None
                results.append(row)
    return {
        'dataset_name': DATASETS[dataset],
        'internal_name': dataset,
        'datasets': [DATASETS[dataset]],
        'results': results,
        'speedup_metadata': {
            'description': 'speedup_percent: Performance improvement compared to baseline (reordering=none)',
            'calculation': '((reordered_qps - baseline_qps) / baseline_qps) * 100',
            'baseline_matching_tolerance': RECALL_TOLERANCE,
            'null_values': 'speedup_percent is null when no matching baseline found within tolerance',
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src', type=Path, help='directory holding the run CSVs')
    parser.add_argument('gpu', help='GPU key, matching GPU_LABELS in leaderboard.jsx')
    parser.add_argument('--k', default='32', help='graph degree to take (default: 32)')
    parser.add_argument(
        '--out', type=Path, default=Path('src/data'), help='data root (default: src/data)'
    )
    args = parser.parse_args()

    runs = collect(args.src, args.k)
    missing = [d for d in DATASETS if d not in runs]
    if missing:
        print(f'no K{args.k} runs for: {", ".join(missing)}', file=sys.stderr)

    out = args.out / args.gpu / 'json'
    out.mkdir(parents=True, exist_ok=True)

    entries = []
    for dataset in DATASETS:
        if dataset not in runs:
            continue
        data = build_dataset(dataset, runs[dataset])
        (out / f'{dataset}.json').write_text(dump(data))
        baseline = sum(1 for r in data['results'] if r['reordering'] == 'none')
        entries.append({
            'internal_name': dataset,
            'display_name': DATASETS[dataset],
            'file_path': f'{args.gpu}/json/{dataset}.json',
            'result_count': len(data['results']),
            'baseline_count': baseline,
            'reordered_count': len(data['results']) - baseline,
        })
        print(f'{dataset}: {len(data["results"])} results')

    index = {
        'datasets': entries,
        'total_datasets': len(entries),
        'total_results': sum(e['result_count'] for e in entries),
        'total_baseline': sum(e['baseline_count'] for e in entries),
        'total_reordered': sum(e['reordered_count'] for e in entries),
    }
    (out / 'index.json').write_text(dump(index))
    print(f'wrote {len(entries)} datasets to {out}')


if __name__ == '__main__':
    main()
