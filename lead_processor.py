import pandas as pd
import re
import io
import os
from database import lead_exists, insert_leads_bulk

def detect_columns(df):
    """
    Tenta detectar automaticamente as colunas de Nome, Email e Telefone.
    Retorna um dicionário com mapeamento das colunas.
    """
    col_mapping = {"name": None, "email": None, "phone": None}
    
    # Converter colunas para string minúscula para comparação
    columns = [str(col).strip().lower() for col in df.columns]
    original_cols = list(df.columns)
    
    # Padrões Regex para detecção
    name_patterns = [r'nome', r'name', r'lead', r'cliente', r'contato', r'artista']
    email_patterns = [r'email', r'e-mail', r'mail', r'correio']
    phone_patterns = [r'tel', r'phone', r'fone', r'celular', r'wpp', r'whatsapp', r'telefone']
    
    # 1. Tentar mapear por correspondência exata ou padrões comuns
    for i, col in enumerate(columns):
        orig_col = original_cols[i]
        
        # Mapear Nome
        if col_mapping["name"] is None:
            if any(re.search(pat, col) for pat in name_patterns):
                col_mapping["name"] = orig_col
                continue
                
        # Mapear Email
        if col_mapping["email"] is None:
            if any(re.search(pat, col) for pat in email_patterns):
                col_mapping["email"] = orig_col
                continue
                
        # Mapear Telefone
        if col_mapping["phone"] is None:
            if any(re.search(pat, col) for pat in phone_patterns):
                col_mapping["phone"] = orig_col
                continue

    # 2. Heurística Secundária: Se não encontrou Nome, pega a primeira coluna de texto
    if col_mapping["name"] is None and len(original_cols) > 0:
        col_mapping["name"] = original_cols[0]
        
    # 3. Heurística Secundária para Email e Telefone (analisando os dados da coluna)
    for col in original_cols:
        if col == col_mapping["name"]:
            continue
            
        # Obter amostra de dados não nulos
        sample = df[col].dropna().head(10).astype(str).tolist()
        if not sample:
            continue
            
        # Verificar se parece e-mail (contém @)
        if col_mapping["email"] is None:
            email_like = sum(1 for val in sample if "@" in val and "." in val)
            if email_like / len(sample) > 0.6:
                col_mapping["email"] = col
                continue
                
        # Verificar se parece telefone (contém muitos números, traços, parênteses)
        if col_mapping["phone"] is None:
            phone_like = sum(1 for val in sample if len(re.sub(r'\D', '', val)) >= 8)
            if phone_like / len(sample) > 0.6:
                col_mapping["phone"] = col
                continue

    return col_mapping

def read_file_to_df(file_bytes, filename):
    """
    Lê os bytes de um arquivo Excel ou CSV em um DataFrame.
    """
    ext = os.path.splitext(filename)[1].lower()
    
    if ext == '.csv':
        # Tentar ler com separador vírgula e ponto-e-vírgula
        try:
            return pd.read_csv(io.BytesIO(file_bytes), sep=None, engine='python', dtype=str)
        except Exception:
            return pd.read_csv(io.BytesIO(file_bytes), dtype=str)
    elif ext in ['.xlsx', '.xls']:
        return pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    else:
        raise ValueError("Formato de arquivo não suportado. Envie apenas arquivos .xlsx, .xls ou .csv")

def process_new_leads_sheet(file_bytes, filename, custom_mapping=None):
    """
    Processa uma planilha de novos leads:
    - Identifica colunas
    - Compara com o banco de dados (Nome, Email ou Telefone)
    - Remove os duplicados
    - Insere os novos no banco de dados
    - Retorna os bytes do arquivo filtrado e estatísticas
    """
    df = read_file_to_df(file_bytes, filename)
    total_original = len(df)
    
    if total_original == 0:
        return None, {
            "total_rows": 0,
            "new_leads": 0,
            "duplicates_removed": 0,
            "col_mapping": {}
        }
        
    # Obter ou detectar mapeamento de colunas
    mapping = custom_mapping or detect_columns(df)
    
    name_col = mapping.get("name")
    email_col = mapping.get("email")
    phone_col = mapping.get("phone")
    
    # Se não temos nem a coluna de Nome, não conseguimos fazer muito
    if not name_col:
        raise ValueError("Não foi possível identificar a coluna de Nome na planilha.")

    keep_indices = []
    new_leads_to_insert = []
    duplicates_count = 0
    
    # Percorrer cada linha e validar
    for idx, row in df.iterrows():
        name_val = row[name_col] if name_col in df.columns else None
        email_val = row[email_col] if email_col and email_col in df.columns else None
        phone_val = row[phone_col] if phone_col and phone_col in df.columns else None
        
        # Ignorar linhas vazias de nome
        if pd.isna(name_val) or str(name_val).strip() == "":
            # Manter na planilha para não perder dados nulos aleatórios, ou descartar? 
            # Geralmente, lead sem nome é descartado ou ignorado na verificação. Vamos manter.
            keep_indices.append(idx)
            continue
            
        name = str(name_val).strip()
        email = str(email_val).strip() if not pd.isna(email_val) else None
        phone = str(phone_val).strip() if not pd.isna(phone_val) else None
        
        # Verificar duplicidade no banco
        if lead_exists(name, email, phone):
            duplicates_count += 1
        else:
            # É um lead novo!
            keep_indices.append(idx)
            new_leads_to_insert.append({
                "name": name,
                "email": email,
                "phone": phone
            })

    # Filtrar o dataframe para manter apenas os novos
    filtered_df = df.loc[keep_indices]
    
    # Inserir novos leads no banco (bulk insert para alta performance)
    inserted_count = insert_leads_bulk(new_leads_to_insert)
    
    # Gerar o arquivo de saída em bytes
    output_bytes = io.BytesIO()
    ext = os.path.splitext(filename)[1].lower()
    
    if ext == '.csv':
        filtered_df.to_csv(output_bytes, index=False, sep=';', encoding='utf-8-sig')
    else:
        with pd.ExcelWriter(output_bytes, engine='openpyxl') as writer:
            filtered_df.to_excel(writer, index=False)
            
    output_bytes.seek(0)
    
    return output_bytes.getvalue(), {
        "total_rows": total_original,
        "new_leads": inserted_count,
        "duplicates_removed": duplicates_count,
        "col_mapping": {
            "name": name_col,
            "email": email_col,
            "phone": phone_col
        }
    }

def import_historical_sheet(file_bytes, filename, custom_mapping=None):
    """
    Importa uma planilha histórica (leads já enviados):
    - Alimenta o banco de dados
    - Retorna o número de novos leads inseridos
    """
    df = read_file_to_df(file_bytes, filename)
    total_rows = len(df)
    
    if total_rows == 0:
        return 0, {}
        
    mapping = custom_mapping or detect_columns(df)
    
    name_col = mapping.get("name")
    email_col = mapping.get("email")
    phone_col = mapping.get("phone")
    
    if not name_col:
        raise ValueError("Não foi possível identificar a coluna de Nome na planilha.")
        
    leads_to_insert = []
    
    for idx, row in df.iterrows():
        name_val = row[name_col] if name_col in df.columns else None
        email_val = row[email_col] if email_col and email_col in df.columns else None
        phone_val = row[phone_col] if phone_col and phone_col in df.columns else None
        
        if pd.isna(name_val) or str(name_val).strip() == "":
            continue
            
        leads_to_insert.append({
            "name": str(name_val).strip(),
            "email": str(email_val).strip() if not pd.isna(email_val) else None,
            "phone": str(phone_val).strip() if not pd.isna(phone_val) else None
        })
        
    inserted_count = insert_leads_bulk(leads_to_insert)
    
    return inserted_count, {
        "total_rows": total_rows,
        "col_mapping": {
            "name": name_col,
            "email": email_col,
            "phone": phone_col
        }
    }
