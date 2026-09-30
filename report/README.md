# Relatório da lecture OFDM

Gere as tabelas e figuras a partir dos dados brutos:

```bash
eval "$(mise env -s bash)"
make bench SUITE=smoke
make analyze
```

O arquivo `report/LATEST` aponta para a execução analisada. Cada diretório contém
README, tabelas CSV, figuras PNG/SVG e proveniência. Os diretórios de execução são
locais e regeneráveis; `results/<run_id>/raw/` conserva cada processo observado.

O smoke demonstra o caminho inteiro com as quatro linguagens. Uma repetição,
carga curta, ausência de cooldown e turbo ligado impedem usar esses valores
como comparação publicada. M7 valida a qualidade estatística; M8 faz perfil de execução
e calibração; M9 coleta o protocolo completo; M10 fecha a interpretação.

Para a lecture, siga `LECTURE.md`: modelo físico, operador numérico, artefato de
verificação e medição são evidências diferentes. A figura de estágios mostra
onde o trabalho acontece; seu resíduo não é decomposição exata de custo.
