# Segurança do FI$H License System

Nunca publique neste repositório arquivos `.env`, tokens do GitHub, `LICENSE_API_KEY`, chaves privadas, arquivos de licença reais ou caches de ativação. O arquivo `.env.example` contém apenas nomes e valores ilustrativos.

O arquivo `data/licenses.example.json` é somente um modelo. O banco local real deve permanecer em `data/licenses.local.json`, que está excluído pelo `.gitignore`.

O gerador administrativo deve ser executado apenas pelo administrador. Não distribua o token administrativo junto com o FI$H e não o inclua em código, commits, screenshots ou mensagens públicas.

Se um segredo for publicado por engano, revogue-o imediatamente no provedor correspondente, gere outro e remova o valor também do histórico do Git. Apagar o arquivo no commit mais recente não é suficiente para considerar o segredo seguro.
