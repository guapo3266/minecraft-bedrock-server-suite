import os
import re

files_to_process = [
    'server_wrapper.py', 'auto_backup.py', 'restore_backup.py', 
    'enable_beta_apis.py', 'enable_beta_apis_v2.py'
]

replacements = [
    # Remove AI headers
    (r'# ═══════════════════════════════════════════════════════════════\n', '# ---\n'),
    # Docstrings in server_wrapper
    (r'\"\"\"\nserver_wrapper\.py — Wrapper.*?\"\"\"', '\"\"\"\nScript principal para manejar el servidor y hacer backups.\nOjalá no se rompa.\n\"\"\"', re.DOTALL),
    (r'# ADVERTENCIA: Las detecciones de jugadores.*?# Si sospechas que esto fallo, revisa los backups en caliente\.', '# Ojo: dependo de los textos en ingles del log para saber si hay jugadores.\n# Si en alguna version de Bedrock lo traducen, esto va a dejar de funcionar.', re.DOTALL),
    (r'# ESTADO GLOBAL \(protegido por state_lock\)', '# Variables globales (metí un lock para que no se pisen entre hilos)'),
    (r'\"\"\"Envía un comando al servidor de forma segura ignorando tuberías rotas o stdin cerrado\.\"\"\"', '\"\"\"Le tira un comando al server y si el pipe falla hace la vista gorda.\"\"\"'),
    (r'# PROCESO WORKER: Compresión en E/S aislada', '# Worker para comprimir el zip sin trabar el server'),
    (r'\"\"\"Función de nivel superior \(picklable\) para ejecutar en un proceso aislado\.\"\"\"', '\"\"\"Funcion separada para el multiprocessing.\"\"\"'),
    (r'# HILO scheduler: Reloj maestro, Watchdog ATÓMICO y Sincronización', '# Hilo principal que revisa cada segundo si hay que hacer backup o apagar'),
    (r'\"\"\"Reloj maestro defensivo con evaluación e intervenciones de estado 100% atómicas\.\"\"\"', '\"\"\"Loop infinito que despacha backups. Le puse varios candados, parece seguro.\"\"\"'),
    (r'# --- EVALUACIÓN DE ESTADO 100% ATÓMICA ---', '# Reviso el estado con candado por si acaso'),
    (r'# --- EJECUCIÓN DE COMANDOS FUERA DEL LOCK \(Cero riesgo de deadlock/TOCTOU\) ---', '# Mando los comandos aca afuera para no trabar todo'),
    
    # Docstrings in auto_backup.py
    (r'\"\"\"\nauto_backup\.py — Motor.*?\"\"\"', '\"\"\"\nScript que hace la compresion ZIP y borra los viejos.\n\"\"\"', re.DOTALL),
    (r'# UTILIDAD: Limpieza de nombres de mundo', '# Para limpiar caracteres raros de la carpeta'),
    (r'\"\"\"Limpia caracteres no permitidos.*?\"\"\"', '\"\"\"Saca caracteres feos para no romper el zip.\"\"\"'),
    
    # restore_backup
    (r'\"\"\"\nrestore_backup\.py —.*?\"\"\"', '\"\"\"\nScript interactivo para restaurar un zip.\n\"\"\"', re.DOTALL),
    
    # enable_beta
    (r'\"\"\"\nenable_beta_apis.*?\"\"\"', '\"\"\"\nScript medio experimental para editar el level.dat.\n\"\"\"', re.DOTALL),
]

repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for filename in files_to_process:
    filepath = os.path.join(repo_dir, filename)
    if not os.path.exists(filepath): continue
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    for pattern, replacement, *flags in replacements:
        if flags:
            content = re.sub(pattern, replacement, content, flags=flags[0])
        else:
            content = re.sub(pattern, replacement, content)
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

print('Hecho')
