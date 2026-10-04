import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# 1. Configuração de Diretórios
PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
META_DIR = RAW_DIR / ".meta"

def criar_diretorios():
    """Garante que a pasta data/raw exista antes de salvar qualquer coisa."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

# === Módulo de Idempotência ===
def _carregar_checkpoint(nome_base):
    """Verifica se a fonte de dados já foi baixada com sucesso (via .meta)."""
    checkpoint_path = META_DIR / f".checkpoint_{nome_base}.json"
    if checkpoint_path.exists():
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def _salvar_checkpoint(nome_base, caminho_arquivo, qtd_registros):
    """Salva um recibo (checkpoint) com Hash provando que o download já foi feito."""
    checkpoint_path = META_DIR / f".checkpoint_{nome_base}.json"
    import hashlib
    sha256 = hashlib.sha256()
    sha256.update(caminho_arquivo.read_bytes())
    
    dados = {
        "fonte": nome_base,
        "arquivo": str(caminho_arquivo),
        "hash_sha256": sha256.hexdigest(),
        "total_registros": qtd_registros,
        "coletado_em": datetime.now().isoformat()
    }
    
    with open(checkpoint_path, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=2)

# === Módulo de Coleta ===
def coletar_ibge():
    """Consome a API do IBGE para obter a população de todos os municípios."""
    url = "https://apisidra.ibge.gov.br/values/t/4709/n6/all/v/93/p/all"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Erro ao acessar IBGE: {e}")
        return None

def coletar_pncp(ano):
    """Consome a API do PNCP (Contratos) com paginação e backoff exponencial."""
    contratos = []
    pagina = 1
    tamanho_pagina = 50 
    
    data_inicial = f"{ano}0101"
    data_final = f"{ano}1231"

    while True:
        url = f"https://pncp.gov.br/api/consulta/v1/contratos?dataInicial={data_inicial}&dataFinal={data_final}&pagina={pagina}&tamanhoPagina={tamanho_pagina}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        max_retries = 3
        retry_delay = 5
        sucesso = False
        
        for tentativa in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    if response.status == 200:
                        dados_pagina = json.loads(response.read().decode('utf-8'))
                        itens = dados_pagina.get('data', []) if isinstance(dados_pagina, dict) else dados_pagina
                        
                        if not itens:
                            return contratos 
                            
                        contratos.extend(itens)
                        print(f"PNCP: Página {pagina} lida ({len(itens)} contratos)")
                        sucesso = True
                        
                        if len(itens) < tamanho_pagina:
                            return contratos 
                        break 
                        
            except urllib.error.HTTPError as e:
                if e.code >= 500:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    break
            except Exception as e:
                time.sleep(retry_delay)
                retry_delay *= 2
                
        if not sucesso:
            break
            
        time.sleep(2)
        pagina += 1
        
        # Parada de segurança em 200 páginas (10.000 contratos)
        if pagina > 200:
            break
            
    return contratos

def salvar_raw(dados, nome_base):
    if not dados:
        print(f"Nenhum dado para salvar em {nome_base}.")
        return None
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = RAW_DIR / f"{nome_base}_{timestamp}.json"
    
    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        
    _salvar_checkpoint(nome_base, caminho, len(dados))
    return caminho

def main():
    print("=== Iniciando Pipeline de Ingestão (Obtain) ===\n")
    criar_diretorios()
    
    # --- Passo B: Coletar IBGE ---
    fonte_ibge = "ibge_populacao"
    if _carregar_checkpoint(fonte_ibge):
        print(f"[SKIP] Pulando {fonte_ibge}: Os dados já foram coletados anteriormente.")
    else:
        salvar_raw(coletar_ibge(), fonte_ibge)
    
    # --- Passo C: Coletar PNCP ---
    ano_alvo = 2026
    fonte_pncp = f"pncp_contratos_{ano_alvo}"
    if _carregar_checkpoint(fonte_pncp):
        print(f"[SKIP] Pulando {fonte_pncp}: Os dados já foram coletados anteriormente.")
    else:
        salvar_raw(coletar_pncp(ano_alvo), fonte_pncp)
    
if __name__ == "__main__":
    main()