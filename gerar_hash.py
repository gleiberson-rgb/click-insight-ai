"""
Utilitario para gerar hash bcrypt de senha (uso: adicionar/trocar usuarios em auth_config.yaml).

Uso:
    python gerar_hash.py
    > Digite a senha: ********
    > Hash bcrypt: $2b$12$...

Depois cole o hash em auth_config.yaml no campo 'password' do usuario.
"""
import bcrypt
import getpass

senha = getpass.getpass("Digite a senha do novo usuario: ")
confirma = getpass.getpass("Confirme a senha: ")
if senha != confirma:
    print("Senhas nao conferem.")
    raise SystemExit(1)
if len(senha) < 8:
    print("ATENCAO: senha curta. Recomenda-se 12+ caracteres.")
print("Hash bcrypt (cole em auth_config.yaml):")
print(bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode())
