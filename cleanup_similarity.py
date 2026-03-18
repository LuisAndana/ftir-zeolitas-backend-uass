"""
Script para limpiar similarity_result.py completamente
Ejecutar en tu carpeta del proyecto: python cleanup_similarity.py
"""

import os

print("\n" + "="*70)
print("🧹 LIMPIANDO similarity_result.py")
print("="*70 + "\n")

filepath = "app/models/similarity_result.py"

if not os.path.exists(filepath):
    print(f"❌ {filepath} no encontrado")
    print("\nIntentando encontrar el archivo...")
    
    # Buscar en subdirectorios
    for root, dirs, files in os.walk("."):
        if "similarity_result.py" in files:
            filepath = os.path.join(root, "similarity_result.py")
            print(f"✅ Encontrado en: {filepath}")
            break

if os.path.exists(filepath):
    print(f"Procesando: {filepath}\n")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
    
    print(f"Total de líneas: {len(lines)}\n")
    
    # Mostrar las líneas problemáticas
    print("Líneas con relaciones problemáticas:")
    
    new_lines = []
    for i, line in enumerate(lines):
        line_num = i + 1
        
        # Eliminar líneas que contengan back_populates="search_results"
        if 'back_populates="search_results"' in line:
            print(f"   ❌ Línea {line_num}: {line.strip()}")
            continue
        
        # Eliminar líneas que contengan relationship con search_results
        if 'search_results' in line and 'relationship' in line:
            print(f"   ❌ Línea {line_num}: {line.strip()}")
            continue
        
        new_lines.append(line)
    
    # Guardar archivo limpio
    new_content = '\n'.join(new_lines)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"\n✅ Archivo limpiado")
    print(f"Líneas nuevas: {len(new_lines)}")

else:
    print(f"❌ No se puede encontrar: {filepath}")

print("\n" + "="*70)
print("PRÓXIMOS PASOS:")
print("="*70 + """

1. Resetear BD:
   python -c "from app.core.database import reset_db; reset_db()"

2. Iniciar servidor:
   python main.py

3. Probar:
   curl -X POST http://localhost:8000/api/auth/register \\
     -H "Content-Type: application/json" \\
     -d '{"name":"Test","email":"test@test.com","password":"pass123"}'

✅ Esperado: 201 Created
""")

print()
