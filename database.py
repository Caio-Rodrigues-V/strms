import sqlite3
import re
import os

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(DATA_DIR, "leads.db")

# Garantir que a pasta de dados exista (necessário se for montado um volume externo no Railway)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def normalize_name(name):
    if not isinstance(name, str):
        return ""
    name = name.strip().lower()
    name = re.sub(r'\s+', ' ', name)
    if name in ["nan", "none", "null", "undefined", "-", ""]:
        return ""
    return name

def normalize_email(email):
    if not isinstance(email, str):
        return ""
    email = email.strip().lower()
    if email in ["nan", "none", "null", "undefined", "-", ""]:
        return ""
    return email

def normalize_phone(phone):
    if not isinstance(phone, (str, int, float)):
        return ""
    phone_str = str(phone)
    phone_digits = re.sub(r'\D', '', phone_str)
    # Se o telefone resultante for muito curto (menos de 4 dígitos), desconsiderar
    if len(phone_digits) < 4:
        return ""
    return phone_digits

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Criar tabela de leads
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        normalized_name TEXT NOT NULL,
        normalized_email TEXT,
        normalized_phone TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Criar índices para consultas rápidas
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_normalized_name ON leads(normalized_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_normalized_email ON leads(normalized_email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_normalized_phone ON leads(normalized_phone)")
    
    conn.commit()
    conn.close()

def lead_exists(name, email=None, phone=None):
    norm_name = normalize_name(name)
    norm_email = normalize_email(email)
    norm_phone = normalize_phone(phone)
    
    if not norm_name and not norm_email and not norm_phone:
        return False
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    conditions = []
    params = []
    
    # Busca por nome (obrigatório se fornecido)
    if norm_name:
        conditions.append("normalized_name = ?")
        params.append(norm_name)
        
    # Busca por email (se fornecido)
    if norm_email:
        conditions.append("normalized_email = ?")
        params.append(norm_email)
        
    # Busca por telefone (se fornecido)
    if norm_phone:
        conditions.append("normalized_phone = ?")
        params.append(norm_phone)
        
    if not conditions:
        conn.close()
        return False
        
    # Usar OR para bater se QUALQUER um dos identificadores já existir
    query = f"SELECT 1 FROM leads WHERE {' OR '.join(conditions)} LIMIT 1"
    cursor.execute(query, params)
    row = cursor.fetchone()
    
    conn.close()
    return row is not None

def insert_lead(name, email=None, phone=None):
    norm_name = normalize_name(name)
    if not norm_name:
        return False
        
    norm_email = normalize_email(email)
    norm_phone = normalize_phone(phone)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
        INSERT INTO leads (name, email, phone, normalized_name, normalized_email, normalized_phone)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (name, email, phone, norm_name, norm_email, norm_phone))
        conn.commit()
        success = True
    except sqlite3.Error:
        success = False
    finally:
        conn.close()
        
    return success

def insert_leads_bulk(leads_list):
    """
    Insere múltiplos leads em uma única transação.
    Cada elemento de leads_list deve ser um dicionário:
    {'name': '...', 'email': '...', 'phone': '...'}
    """
    if not leads_list:
        return 0
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    inserted_count = 0
    
    # Criar uma transação
    try:
        for lead in leads_list:
            name = lead.get('name')
            email = lead.get('email')
            phone = lead.get('phone')
            
            norm_name = normalize_name(name)
            if not norm_name:
                continue
                
            norm_email = normalize_email(email)
            norm_phone = normalize_phone(phone)
            
            # Verificar se já existe antes de inserir no bulk para evitar duplicados internos
            # Como a transação está aberta, podemos buscar
            conditions = []
            params = []
            
            if norm_name:
                conditions.append("normalized_name = ?")
                params.append(norm_name)
            if norm_email:
                conditions.append("normalized_email = ?")
                params.append(norm_email)
            if norm_phone:
                conditions.append("normalized_phone = ?")
                params.append(norm_phone)
                
            if conditions:
                query = f"SELECT 1 FROM leads WHERE {' OR '.join(conditions)} LIMIT 1"
                cursor.execute(query, params)
                if cursor.fetchone() is not None:
                    continue # Já existe, pula
            
            cursor.execute("""
            INSERT INTO leads (name, email, phone, normalized_name, normalized_email, normalized_phone)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (name, email, phone, norm_name, norm_email, norm_phone))
            inserted_count += 1
            
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Erro no bulk insert: {e}")
        inserted_count = 0
    finally:
        conn.close()
        
    return inserted_count

def get_leads_paginated(page=1, page_size=50, search=""):
    offset = (page - 1) * page_size
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT id, name, email, phone, created_at FROM leads"
    count_query = "SELECT COUNT(*) FROM leads"
    params = []
    
    if search:
        search_term = f"%{search.strip().lower()}%"
        query += " WHERE normalized_name LIKE ? OR normalized_email LIKE ? OR normalized_phone LIKE ?"
        count_query += " WHERE normalized_name LIKE ? OR normalized_email LIKE ? OR normalized_phone LIKE ?"
        params = [search_term, search_term, search_term]
        
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    
    # Pegar total
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    # Pegar registros da página
    cursor.execute(query, params + [page_size, offset])
    rows = cursor.fetchall()
    
    leads = []
    for row in rows:
        leads.append({
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "created_at": row["created_at"]
        })
        
    conn.close()
    return leads, total

def get_total_leads():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM leads")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def clear_all_leads():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM leads")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='leads'")
    conn.commit()
    conn.close()
