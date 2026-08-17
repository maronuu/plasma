import React from 'react';
import datasetIndex from '@/data/a100/json/index.json';

// Vite splits these into one chunk per dataset, so a page load only fetches the
// ~85KB the reader actually selected.
const DATASETS = import.meta.glob('../data/a100/json/*.json');
const datasetLoader = (internalName) =>
  DATASETS[`../data/a100/json/${internalName}.json`];

// Same palette as the standalone leaderboard site (echarts' "vintage").
const PALETTE = [
  '#d87c7c',
  '#919e8b',
  '#d7ab82',
  '#6e7074',
  '#61a0a8',
  '#efa18d',
  '#787464',
  '#cc7e63',
  '#724e58',
  '#4b565b',
];

// Fixed orders so a given index or algorithm keeps its colour across charts,
// which is the whole point of showing them side by side.
const INDEX_ORDER = ['cagra', 'diskann', 'nsg'];
const REORDERING_ORDER = [
  'indegree',
  'outdegree',
  'hubsort',
  'gorder',
  'rcm',
  'random',
];

// The paper's own spelling, which the raw data flattens.
const REORDERING_LABELS = {
  indegree: 'Indegree Sort',
  outdegree: 'Outdegree Sort',
  hubsort: 'Hub Sort',
  gorder: 'GOrder',
  rcm: 'RCM',
  random: 'Random',
};

const reorderingLabel = (r) =>
  REORDERING_LABELS[r] ?? r.charAt(0).toUpperCase() + r.slice(1);

const formatQps = (v) => {
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return v.toFixed(0);
};

/**
 * Recall-QPS leaderboard chart.
 *
 * @param {Object} props
 * @param {boolean} [props.showSpeedup=false] plot QPS improvement instead of QPS
 * @param {string} [props.selectedIndex] restrict to one graph index (cagra|diskann|nsg)
 * @param {string} [props.dataset] initial dataset (defaults to the first one)
 * @param {string} [props.height='420px']
 */
class Chart extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      // echarts touches `window`, so it must stay out of the SSG pass.
      ReactECharts: null,
      dataset: props.dataset ?? datasetIndex.datasets[0]?.internal_name ?? '',
      data: null,
      reordering: 'none',
    };
  }

  async componentDidMount() {
    const [{ default: ReactECharts }, echarts] = await Promise.all([
      import('echarts-for-react'),
      import('echarts'),
    ]);
    echarts.registerTheme('vintage', {
      color: PALETTE,
      backgroundColor: 'transparent',
      graph: { color: PALETTE },
    });
    this.setState({ ReactECharts });
    this.loadDataset(this.state.dataset);
  }

  async loadDataset(internalName) {
    const load = datasetLoader(internalName);
    if (!load) return;
    const mod = await load();
    this.setState({ dataset: internalName, data: mod.default ?? mod });
  }

  option() {
    const { showSpeedup, selectedIndex } = this.props;
    const results = this.state.data.results;

    let rows = showSpeedup
      ? results.filter(
          (r) => r.reordering !== 'none' && r.speedup_percent !== null
        )
      : results.filter((r) => r.reordering === this.state.reordering);
    if (selectedIndex) rows = rows.filter((r) => r.index === selectedIndex);

    // In speedup mode one line per reordering algorithm, otherwise one per index.
    const groups = (showSpeedup ? REORDERING_ORDER : INDEX_ORDER).filter((g) =>
      rows.some((r) => (showSpeedup ? r.reordering : r.index) === g)
    );

    const series = groups.map((group) => {
      const points = rows
        .filter((r) => (showSpeedup ? r.reordering : r.index) === group)
        .sort((a, b) => a.recall - b.recall);
      return {
        name: showSpeedup ? reorderingLabel(group) : group.toUpperCase(),
        type: 'line',
        data: points.map((r) => [
          r.recall,
          showSpeedup ? r.speedup_percent : r.qps,
        ]),
        symbol: 'circle',
        symbolSize: 5,
        smooth: false,
        lineStyle: { width: 2 },
        ...(showSpeedup ? { areaStyle: { opacity: 0.1 } } : {}),
      };
    });

    return {
      // Six charts all initialise at page load, far below the fold, so the
      // entrance animation is motion nobody sees and CPU nobody gets back.
      animation: false,
      tooltip: {
        trigger: 'item',
        formatter: (params) => {
          const [recall, value] = params.value;
          const head = `<strong>${params.seriesName}</strong>`;
          const body = showSpeedup
            ? `Speedup: ${value.toFixed(2)}%`
            : `QPS: ${Math.round(value).toLocaleString()}`;
          return `<div>${head}<br/>${body}<br/>Recall: ${(recall * 100).toFixed(1)}%</div>`;
        },
      },
      legend: { data: series.map((s) => s.name), top: 0, type: 'plain' },
      grid: {
        left: '12%',
        right: '5%',
        bottom: '10%',
        top: '18%',
        containLabel: true,
      },
      xAxis: {
        type: 'value',
        name: 'Recall',
        nameLocation: 'middle',
        nameGap: 28,
        min: 'dataMin',
        max: 'dataMax',
        axisLabel: { formatter: (v) => `${(v * 100).toFixed(0)}%` },
      },
      yAxis: {
        type: 'value',
        name: showSpeedup ? 'QPS improvement (%)' : 'QPS',
        nameLocation: 'middle',
        nameGap: 50,
        scale: true,
        axisLabel: {
          formatter: showSpeedup ? (v) => `${v.toFixed(0)}%` : formatQps,
        },
      },
      series,
    };
  }

  render() {
    const { showSpeedup, selectedIndex, height = '420px' } = this.props;
    const { ReactECharts, data } = this.state;
    const available = data
      ? new Set(data.results.map((r) => r.reordering))
      : new Set();
    const reorderings = ['none', ...REORDERING_ORDER].filter((r) =>
      available.has(r)
    );

    return (
      <div className="uk-margin-small-bottom">
        <div className="uk-grid-small uk-child-width-1-2" data-uk-grid>
          <div>
            <select
              className="uk-select uk-form-small"
              value={this.state.dataset}
              onChange={(e) => this.loadDataset(e.target.value)}
              aria-label="Dataset"
            >
              {datasetIndex.datasets.map((d) => (
                <option key={d.internal_name} value={d.internal_name}>
                  {d.display_name}
                </option>
              ))}
            </select>
          </div>
          <div>
            {showSpeedup ? (
              <span className="uk-text-meta">
                {selectedIndex ? selectedIndex.toUpperCase() : 'All indices'}
              </span>
            ) : (
              <select
                className="uk-select uk-form-small"
                value={this.state.reordering}
                onChange={(e) => this.setState({ reordering: e.target.value })}
                aria-label="Reordering"
              >
                {reorderings.map((r) => (
                  <option key={r} value={r}>
                    {r === 'none'
                      ? 'Baseline (no reordering)'
                      : `${reorderingLabel(r)} reordering`}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
        {ReactECharts && data ? (
          <ReactECharts
            option={this.option()}
            theme="vintage"
            style={{ width: '100%', height }}
            notMerge={true}
            lazyUpdate={true}
          />
        ) : (
          <div
            className="uk-flex uk-flex-center uk-flex-middle uk-text-meta"
            style={{ height }}
          >
            Loading chart...
          </div>
        )}
      </div>
    );
  }
}

export default class Leaderboard extends React.Component {
  render() {
    return (
      <div>
        <h4>Recall vs. QPS</h4>
        <p>
          The trade-off between <b>Recall</b> (accuracy) and <b>QPS</b> (queries
          per second). Upper-right is better. Pick a dataset and a reordering
          algorithm, or compare two datasets side by side.
        </p>
        <div className="uk-child-width-1-2@m uk-grid-small" data-uk-grid>
          <div>
            <Chart dataset="sift-128-euclidean" />
          </div>
          <div>
            <Chart dataset="c45m-1536-ip" />
          </div>
        </div>

        <h4 className="uk-margin-top">Reordering effect</h4>
        <p>
          QPS improvement over the un-reordered baseline, per reordering
          algorithm. Above the zero line means reordering paid off.
        </p>
        <div className="uk-child-width-1-2@m uk-grid-small" data-uk-grid>
          <div>
            <Chart showSpeedup={true} selectedIndex="cagra" dataset="deep10m" />
          </div>
          <div>
            <Chart
              showSpeedup={true}
              selectedIndex="cagra"
              dataset="c45m-1536-ip"
            />
          </div>
          <div>
            <Chart
              showSpeedup={true}
              selectedIndex="nsg"
              dataset="sift-128-euclidean"
            />
          </div>
          <div>
            <Chart showSpeedup={true} selectedIndex="nsg" dataset="deep10m" />
          </div>
        </div>
        <span className="uk-text-meta">
          All measurements on a single NVIDIA A100 80GB.
        </span>
      </div>
    );
  }
}
