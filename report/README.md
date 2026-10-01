# Relatório da lecture OFDM

O experimento comparativo está adiado por instrução do usuário. Nesta etapa,
valide o código e visualize o plano sem coletar dados:

```bash
eval "$(mise env -s bash)"
make check
make bench-plan TURBO=on
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

Quando houver autorização para coletar e uma execução completa, `make analyze
RUN=/caminho/da/execucao` regenera tabelas e figuras. O gerador rejeita coletas
incompletas, hashes inválidos e configurações diferentes misturadas. Vazão e
razões relativas só aparecem para cargas fixas de desempenho. A coleta M9
interrompida não é fonte de um relatório final; nenhuma conclusão de velocidade
ou estabilidade em dez minutos foi produzida nesta continuação.
