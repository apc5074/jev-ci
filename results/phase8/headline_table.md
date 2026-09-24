# Headline results (evaluation, n=113)

| Method | FDR@5% | FDR@10% | FDR@20% | MRR | APFD | Median NFTR | Cost/Bug |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 0.0696 | 0.1229 | 0.2277 | 0.0826 | 0.5201 | 0.4780 | — |
| BM25 | 0.6372 | 0.7345 | 0.8496 | 0.5096 | 0.9005 | 0.0435 | — |
| Embedding | 0.8319 | 0.8850 | 0.9115 | 0.6783 | 0.9396 | 0.0168 | 0.001348 |
| Jev | 0.9027 | **0.9558** | **0.9823** | **0.8222** | **0.9722** | **0.0119** | 0.013878 |
| GPT-5.4 nano | **0.9204** | 0.9204 | 0.9646 | 0.8024 | 0.9638 | 0.0119 | 0.054729 |

Bold marks the numerically best quality value in each column (highest FDR/MRR/APFD; lowest median NFTR). Cost is not bolded.
