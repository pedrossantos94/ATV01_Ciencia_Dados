# Análise de Contratações em Saúde - Brasil

Investigação pautada na metodologia OSEMN para responder à seguinte pergunta analítica: 
**"Entre municípios de mesmo porte populacional, os municípios pequenos pagam um valor per capita muito mais alto em itens de saúde?"**

**Fontes:**
- Contratos de Saúde: PNCP (Portal Nacional de Contratações Públicas) - Acesso API.
- População: SIDRA IBGE - Acesso API.

### Como reproduzir o projeto:
Nenhuma API key é necessária (os dois portais são abertos sem autenticação).

```bash
git clone https://github.com/pedrossantos94/ATV01_Ciencia_Dados
cd <nome-da-pasta>
uv sync
uv run python src/ingest.py
uv run quarto render diagnostico.qmd
uv run python src/transform.py