<div align="center">
<h1>Plasma: A Layout-Aware Benchmark Reveals Memory Layout Matters for Graph-based ANNS on GPU</h1>

<p align="center">
    Yutaro Oguri<sup>1,*</sup> &nbsp;
    Mai Nishimura<sup>2</sup> &nbsp;
    Yusuke Matsui<sup>1</sup>
</p>

<p align="center">
    <sup>1</sup>The University of Tokyo &nbsp;
    <sup>2</sup>OMRON SINIC X Corporation
</p>

<p align="center">
    <sup>*</sup>Work done as an intern at OMRON SINIC X Corporation
</p>

<p align="center">
    <a href="https://arxiv.org/abs/2508.15436"><img src="https://img.shields.io/badge/arXiv-2508.15436-orange" alt="arXiv"></a>
    <a href="https://openreview.net/forum?id=tF70hyyM6V"><img src="https://img.shields.io/badge/OpenReview-tF70hyyM6V-blue" alt="OpenReview"></a>
    <a href="https://omron-sinicx.github.io/plasma"><img src="https://img.shields.io/badge/Project%20Page-plasma-green" alt="Project Page"></a>
</p>

</div>

---

## 📄 Abstract

We propose Plasma, a **P**latform for **L**ayout-**A**ware **S**earch and **M**emory **A**rrangement: a unified evaluation framework for graph-based Approximate Nearest Neighbor Search (ANNS) on GPU that isolates the effects of graph index topology and memory layout.
Graph-based ANNS is essential in modern AI applications such as RAG, and GPU utilization is attracting attention for datasets of millions or more vectors.
Our framework extracts the topology of arbitrary graph-based indices and enables execution under a unified, GPU-optimized search algorithm, specifying the correspondence between vertex IDs and positions on memory to allow arbitrary vertex orderings.
Through comprehensive experiments, we demonstrate that vertex reordering yields up to 80% (typically 10–30%) QPS improvement while preserving search accuracy.

## 🚧 Code

**Code coming soon.**
