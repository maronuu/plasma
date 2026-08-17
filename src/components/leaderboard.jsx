import React from 'react';

// One tab per GPU. Adding a GPU is: drop `src/data/<key>/json/` in place (an
// index.json plus one file per dataset) and add its label here.
const GPU_LABELS = {
  a100: 'NVIDIA A100 80GB',
  rtx6000ada: 'NVIDIA RTX 6000 Ada 48GB',
};

// The per-GPU dataset lists are a couple of KB, so they load with the page.
const INDEXES = import.meta.glob('../data/*/json/index.json', { eager: true });
// The results are not: Vite splits them into one chunk per dataset, so a page
// load only fetches the ~85KB the reader actually selected.
const DATASETS = import.meta.glob('../data/*/json/*.json');

const datasetIndexFor = (gpu) =>
  INDEXES[`../data/${gpu}/json/index.json`]?.default;
const datasetLoader = (gpu, internalName) =>
  DATASETS[`../data/${gpu}/json/${internalName}.json`];

const GPUS = Object.entries(GPU_LABELS).map(([key, label]) => ({
  key,
  label,
  datasets: datasetIndexFor(key)?.datasets ?? [],
}));

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

// The raw data keys DiskANN's index by its library; the paper calls it Vamana.
const INDEX_LABELS = { cagra: 'CAGRA', diskann: 'Vamana', nsg: 'NSG' };

// A uk-label next to a chart takes the colour echarts gives that index's line,
// so the badge and the line read as the same thing.
const INDEX_COLORS = Object.fromEntries(
  INDEX_ORDER.map((key, i) => [key, PALETTE[i]])
);
// NSG's swatch is the palest of the three and holds black far better than
// white, so it is the one that keeps dark text.
const INDEX_TEXT_COLORS = { cagra: '#fff', diskann: '#fff', nsg: '#000' };

const IndexLabel = ({ index }) => (
  <span
    className="uk-label"
    style={{
      backgroundColor: INDEX_COLORS[index],
      color: INDEX_TEXT_COLORS[index] ?? '#fff',
    }}
  >
    {INDEX_LABELS[index] ?? index}
  </span>
);
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
 * @param {string} props.gpu GPU key, one of GPU_LABELS
 * @param {boolean} [props.showSpeedup=false] plot QPS improvement instead of QPS
 * @param {string} [props.selectedIndex] restrict to one graph index (cagra|diskann|nsg)
 * @param {string} [props.dataset] initial dataset (defaults to the first one)
 * @param {string} [props.height='420px']
 */
class Chart extends React.Component {
  constructor(props) {
    super(props);
    const available = datasetIndexFor(props.gpu)?.datasets ?? [];
    // A GPU need not carry every dataset, so an initial pick that this one
    // lacks falls back to whatever it does have.
    const wanted = available.some((d) => d.internal_name === props.dataset)
      ? props.dataset
      : available[0]?.internal_name;
    this.state = {
      // echarts touches `window`, so it must stay out of the SSG pass.
      ReactECharts: null,
      datasets: available,
      dataset: wanted ?? '',
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
    const load = datasetLoader(this.props.gpu, internalName);
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
        name: showSpeedup
          ? reorderingLabel(group)
          : (INDEX_LABELS[group] ?? group.toUpperCase()),
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
              {this.state.datasets.map((d) => (
                <option key={d.internal_name} value={d.internal_name}>
                  {d.display_name}
                </option>
              ))}
            </select>
          </div>
          <div>
            {showSpeedup ? (
              selectedIndex ? (
                <IndexLabel index={selectedIndex} />
              ) : (
                <span className="uk-text-meta">All indices</span>
              )
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

class GpuPanel extends React.Component {
  render() {
    const { gpu, label, datasets } = this.props;
    if (!datasets.length) {
      return (
        <p className="uk-text-meta uk-margin-top">
          Results for {label} are not published yet.
        </p>
      );
    }
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
            <Chart gpu={gpu} dataset="sift-128-euclidean" />
          </div>
          <div>
            <Chart gpu={gpu} dataset="c45m-1536-ip" />
          </div>
        </div>

        <h4 className="uk-margin-top">Reordering effect</h4>
        <p>
          QPS improvement over the un-reordered baseline, per reordering
          algorithm. Above the zero line means reordering paid off.
        </p>
        <div className="uk-child-width-1-2@m uk-grid-small" data-uk-grid>
          <div>
            <Chart
              gpu={gpu}
              showSpeedup={true}
              selectedIndex="cagra"
              dataset="deep10m"
            />
          </div>
          <div>
            <Chart
              gpu={gpu}
              showSpeedup={true}
              selectedIndex="cagra"
              dataset="c45m-1536-ip"
            />
          </div>
          <div>
            <Chart
              gpu={gpu}
              showSpeedup={true}
              selectedIndex="nsg"
              dataset="sift-128-euclidean"
            />
          </div>
          <div>
            <Chart
              gpu={gpu}
              showSpeedup={true}
              selectedIndex="nsg"
              dataset="deep10m"
            />
          </div>
          <div>
            <Chart
              gpu={gpu}
              showSpeedup={true}
              selectedIndex="diskann"
              dataset="gist-960-euclidean"
            />
          </div>
          <div>
            <Chart
              gpu={gpu}
              showSpeedup={true}
              selectedIndex="diskann"
              dataset="deep10m"
            />
          </div>
        </div>
        <span className="uk-text-meta">
          All measurements on a single {label}.
        </span>
      </div>
    );
  }
}

export default class Leaderboard extends React.Component {
  constructor(props) {
    super(props);
    this.state = { active: 0 };
  }

  render() {
    const active = GPUS[this.state.active];
    // UIkit's own tab component would keep the inactive panels in the DOM, and
    // echarts sizes itself to a container that is display:none at init, so the
    // hidden tab's charts come back 200px wide. React owns the switching
    // instead and only the visible panel is mounted; `uk-tab` here is styling.
    return (
      <div>
        <ul className="uk-tab">
          {GPUS.map((g, idx) => (
            <li
              key={'tab-' + g.key}
              className={idx === this.state.active ? 'uk-active' : undefined}
            >
              <a
                href={`#${g.key}`}
                onClick={(e) => {
                  e.preventDefault();
                  this.setState({ active: idx });
                }}
              >
                {g.label}
              </a>
            </li>
          ))}
        </ul>
        <GpuPanel
          key={active.key}
          gpu={active.key}
          label={active.label}
          datasets={active.datasets}
        />
      </div>
    );
  }
}
