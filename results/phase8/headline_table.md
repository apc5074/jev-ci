# Headline results (evaluation, n=125)

| Method | FDR@5% | FDR@10% | FDR@20% | MRR | APFD | Median NFTR | Cost/Bug |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 0.0700 | 0.1240 | 0.2285 | 0.0884 | 0.5206 | 0.4786 | — |
| BM25 | 0.6080 | 0.7360 | 0.8560 | 0.4976 | 0.8987 | 0.0455 | — |
| Embedding | 0.8320 | 0.8800 | 0.9040 | 0.6906 | 0.9376 | 0.0269 | 0.001261 |
| Jev | 0.8160 | 0.8640 | 0.8880 | 0.7464 | 0.8804 | 0.0169 | 0.012545 |
| GPT-5.4 nano | **0.9120** | **0.9120** | **0.9600** | **0.7954** | **0.9595** | **0.0139** | 0.050775 |

Bold marks the numerically best quality value in each column (highest FDR/MRR/APFD; lowest median NFTR). Cost is not bolded.
