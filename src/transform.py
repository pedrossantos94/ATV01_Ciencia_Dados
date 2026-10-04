import json
import numpy as np
import pandas as pd
import pandera.pandas as pa
from pathlib import Path
from pandera.pandas import Column, Check, DataFrameSchema

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
TRUSTED_DIR = PROJECT_ROOT / "data" / "trusted"
QUARENTENA_DIR = PROJECT_ROOT / "data" / "quarentena"

# === 1. O Contrato de Dados ===
# Garante que nenhum dado seja salvo se não atender às expectativas estritas da análise.
CONTRATO = DataFrameSchema(
    columns={
        "numeroContratoEmpenho": Column(str, nullable=False),
        "codigoIbge": Column(str, nullable=False),
        "nomeRazaoSocialFornecedor": Column(str, nullable=False),
        "objetoContrato": Column(str, nullable=False),
        
        "valorGlobal": Column(
            float, 
            Check.greater_than(0.0, error="valor_invalido_ou_negativo"), 
            nullable=False
        ),
        "populacao_cidade": Column(
            int, 
            Check.greater_than(0, error="populacao_nula"), 
            nullable=False
        ),
        "porte_municipio": Column(
            str, 
            Check.isin(["Pequeno", "Médio", "Grande"], error="porte_desconhecido"),
            nullable=False
        ),
        "valor_per_capita": Column(
            float,
            Check.greater_than_or_equal_to(0.0, error="per_capita_negativo"),
            nullable=False
        )
    },
    coerce=True,
    strict=True
)

def carregar_dados():
    """Lê os últimos JSONs intocados na camada Raw."""
    arq_pncp = sorted(RAW_DIR.glob("pncp_contratos_*.json"))[-1]
    arq_ibge = sorted(RAW_DIR.glob("ibge_populacao_*.json"))[-1]
    
    with open(arq_pncp, 'r', encoding='utf-8') as f:
        df_pncp = pd.DataFrame(json.load(f))
    with open(arq_ibge, 'r', encoding='utf-8') as f:
        df_ibge = pd.DataFrame(json.load(f))
        
    df_ibge = df_ibge.rename(columns={"D1C": "codigoIbge", "V": "populacao_cidade"})
    df_ibge = df_ibge[df_ibge['populacao_cidade'].str.isnumeric() == True]
    df_ibge['populacao_cidade'] = df_ibge['populacao_cidade'].astype(int)
    
    return df_pncp, df_ibge

def higienizar(df_pncp, df_ibge):
    """Cruza as tabelas, limpa o texto e calcula a métrica (Feature Engineering)."""
    # 1. Filtro: Manter apenas itens relacionados à saúde
    palavras = ["saúde", "saude", "médico", "medico", "hospital", "clínica", "remédio", "medicamento", "ambulância", "reagente"]
    padrao = "|".join(palavras)
    df_saude = df_pncp[df_pncp['objetoContrato'].str.lower().str.contains(padrao, na=False)].copy()
    
    # 2. Extrai IBGE e cruza as bases
    df_saude['codigoIbge'] = df_saude['unidadeOrgao'].apply(lambda x: x.get('codigoIbge') if isinstance(x, dict) else None)
    df_merge = df_saude.merge(df_ibge[['codigoIbge', 'populacao_cidade']], on='codigoIbge', how='left')
    df_merge['populacao_cidade'] = df_merge['populacao_cidade'].fillna(0)
    
    # 3. Classifica as cidades em Portes
    condicoes = [
        (df_merge['populacao_cidade'] < 50000),
        (df_merge['populacao_cidade'] >= 50000) & (df_merge['populacao_cidade'] < 500000),
        (df_merge['populacao_cidade'] >= 500000)
    ]
    df_merge['porte_municipio'] = np.select(condicoes, ['Pequeno', 'Médio', 'Grande'], default='Pequeno')
    
    # 4. Calcula a razão Per Capita
    df_merge['valor_per_capita'] = np.where(
        df_merge['populacao_cidade'] > 0, 
        df_merge['valorGlobal'] / df_merge['populacao_cidade'], 
        0.0
    )
    
    colunas = ["numeroContratoEmpenho", "codigoIbge", "nomeRazaoSocialFornecedor", "objetoContrato", "valorGlobal", "populacao_cidade", "porte_municipio", "valor_per_capita"]
    return df_merge[colunas].copy()

def tratar_e_validar(df_limpo):
    """Usa Pandera para isolar dados imundos sem parar o processamento (Quarentena)."""
    try:
        df_ok = CONTRATO.validate(df_limpo, lazy=True)
        return df_ok, df_limpo.iloc[0:0].copy()
    except pa.errors.SchemaErrors as erro:
        falhas = erro.failure_cases
        
        # Parada rígida se faltar coluna inteira (Schema Drift)
        if falhas["index"].isna().any():
            raise SystemExit("Contrato quebrado na estrutura. Nada foi gravado.")
            
        # Agrupa todos os motivos de erro da mesma linha em uma única string
        motivo_por_linha = falhas.groupby("index")["check"].agg(lambda s: ", ".join(sorted(set(s))))
        indices = motivo_por_linha.index
        
        df_rejeitado = df_limpo.loc[indices].assign(
            motivo=motivo_por_linha,
            detectado_em=pd.Timestamp.now(tz="UTC")
        )
        
        df_ok = CONTRATO.validate(df_limpo.drop(index=indices))
        return df_ok, df_rejeitado

def main():
    df_pncp, df_ibge = carregar_dados()
    df_limpo = higienizar(df_pncp, df_ibge)
    df_aprovado, df_rejeitado = tratar_e_validar(df_limpo)
    
    TRUSTED_DIR.mkdir(parents=True, exist_ok=True)
    df_aprovado.to_parquet(TRUSTED_DIR / "contratos_saude.parquet", index=False)
    
    if not df_rejeitado.empty:
        QUARENTENA_DIR.mkdir(parents=True, exist_ok=True)
        df_rejeitado.to_parquet(QUARENTENA_DIR / "rejeitados.parquet", index=False)

if __name__ == "__main__":
    main()