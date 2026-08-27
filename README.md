# FI$H License System

Pasta completa para adicionar licenciamento ao FI$H. A solução separa o aplicativo desktop da administração de licenças: o cliente chama uma API HTTPS, enquanto o token do GitHub e as operações de escrita ficam exclusivamente no servidor.

## Estrutura

| Caminho | Função |
|---|---|
| `app/api.py` | Endpoints Flask de saúde, ativação, validação e administração. |
| `app/service.py` | Hash de chave, expiração, ativação e limite de dispositivos. |
| `app/store.py` | Armazenamento local para desenvolvimento e Gist para produção inicial. |
| `client/license_client.py` | Cliente que o FI$H pode importar para HWID, ativação e validação. |
| `admin/license_admin.py` | Geração/cadastro de licenças pelo administrador. |
| `data/licenses.local.json` | Banco local de desenvolvimento; não use como banco comercial definitivo. |
| `.env.example` | Modelo de configuração sem segredos reais. |
| `tests/` | Testes automatizados da regra de licenciamento. |

## Instalação local

Use Python 3.10 ou superior:

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# Linux/macOS
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Copie `.env.example` para `.env` e altere pelo menos `LICENSE_API_KEY`:

```text
LICENSE_API_KEY=uma-chave-administrativa-forte
APP_ENV=development
```

Inicie a API:

```bash
python run.py
```

Teste a saúde da API:

```bash
curl http://127.0.0.1:8080/health
```

## Criar uma licença no banco local

Com a API rodando, execute:

```bash
set LICENSE_API_KEY=uma-chave-administrativa-forte
python admin/license_admin.py --days 30 --plan monthly --max-devices 1
```

O comando exibirá a chave gerada. Para cadastrar uma chave específica:

```bash
python admin/license_admin.py --key FISH7-Q4K9M-2N8TX-PL6RV-Z3A1C --days 30
```

No PowerShell, use `$env:LICENSE_API_KEY=\"uma-chave-administrativa-forte\"`.

## Usar um Gist privado

Crie um Gist privado com um arquivo `licenses.json` contendo:

```json
{
  "schema": 1,
  "licenses": {}
}
```

Configure no `.env`:

```text
GIST_ID=id-do-gist
GIST_FILENAME=licenses.json
GITHUB_TOKEN=token-apenas-no-servidor
```

Reinicie a API. Quando `GIST_ID` e `GITHUB_TOKEN` estiverem definidos, ela usará o Gist; caso contrário, usará `data/licenses.local.json`.

O token nunca deve ser copiado para o FI$H, para o cliente ou para um arquivo distribuído. Para uma operação comercial maior, substitua o Gist por um banco de dados e mantenha o mesmo contrato de API.

## Integrar no FI$H

Exemplo mínimo:

```python
from pathlib import Path
from client import LicenseClient

client = LicenseClient(
    api_base="https://licenca.seudominio.com",
    cache_path=Path("data/license_cache.json"),
)

result = client.activate(chave_digitada)
if not result.get("success"):
    mostrar_erro(result.get("message", "Licença inválida"))
    bloquear_monitor()
else:
    liberar_monitor()
```

Na inicialização, use `client.validate()` e bloqueie as funções do FI$H se a resposta for inválida. O cache local é apenas para melhorar a experiência durante indisponibilidade temporária; não trate o JSON local como autoridade.

## Endpoints

| Método | Endpoint | Proteção | Uso |
|---|---|---|---|
| `GET` | `/health` | Pública | Verifica disponibilidade. |
| `POST` | `/v1/license/activate` | Pública | Envia `key` e `hwid`; associa o dispositivo. |
| `POST` | `/v1/license/validate` | Pública | Confirma status e expiração. |
| `POST` | `/v1/admin/licenses` | `X-Admin-Key` | Cria licença. |
| `PATCH` | `/v1/admin/licenses/<hash>` | `X-Admin-Key` | Altera status, plano, validade ou dispositivos. |

## Testes

```bash
pytest -q
```

Os testes cobrem ativação, repetição no mesmo dispositivo, limite de dispositivos e expiração.

## Antes de publicar

Use HTTPS, não exponha o servidor Flask de desenvolvimento diretamente, troque `LICENSE_API_KEY`, limite acesso aos endpoints administrativos, armazene o token do GitHub como segredo do servidor, adicione rate limiting e logs sem chaves, e configure backups do banco. Se vender assinaturas, atualize a licença por webhook de um provedor de pagamentos e torne o processamento do webhook idempotente.

Este projeto é uma base funcional de desenvolvimento. Ele não inclui credenciais, cobrança real, painel web de administrador nem garantia contra adulteração de um cliente desktop modificado.
# RELATORIOCDI
