# GravaBin

**Versão 1.1.0**

Ferramenta gráfica em Python/Tkinter para **gravar binários em ESP8266/ESP32**
no Linux derivados Debian/Ubuntu; 

Tal ferramenta foi construída para suprir uma necessidade profissional.
"Gravar Controladores em ambientes Linux de forma rápida e prática"

Ideia construída inspirado nos seguintes projetos:
[NodeMCU PyFlasher](https://github.com/marcelstoer/nodemcu-pyflasher)
[Esptool](https://github.com/espressif/esptool)

Este projeto é uma interface gráfica para facilitar operações que já são executadas pelo esptool.

## Recursos

- Detecção automática de portas (`/dev/ttyUSB*`, `/dev/ttyACM*`).
- Seleção de chip (`esp32`, `esp32s2/s3/c3`, `esp8266`).
- Tabela de binários (offset + arquivo `.bin`), com valores típicos pré-preenchidos.
- **Tela inicial** para escolher entre **gravação única**, **gravação
  múltipla** (várias placas ao mesmo tempo, em portas diferentes) e
  **compilador**.
- **Modo compilador** (estilo Arduino IDE 1.8): compila e carrega sketches
  `.ino`, com **gerenciador de placas** e **de bibliotecas**, compartilhando
  placas e bibliotecas com o Arduino IDE. O resultado vira um preset com um
  clique, pronto para a gravação múltipla.
- **Presets em abas** (estilo navegador): salve conjuntos de arquivos/offsets
  e configurações de gravação com um nome e alterne entre eles sem
  reselecionar tudo. Os presets ficam em `~/.config/gravabin/presets.json` e
  são restaurados ao abrir o programa.
- **Exportar/importar presets** (`.gravabin`, já com os binários) para
  compartilhar com outros colaboradores.
- Lista apenas portas USB-serial (as UARTs internas `/dev/ttyS*` são ocultadas).
- Configuração de baud, flash mode (`dio/qio/dout/qout`), freq, size.
- Botões para **Gravar**, **Apagar Flash** e **Ler MAC/Chip**.
- Console em tempo real com saída do `esptool`.
- **Monitor serial** embutido: acompanhe o que o firmware imprime na porta,
  com baud próprio, data/hora em cada linha, exportação do log e opção de
  reabrir o monitor automaticamente após gravar/apagar.
- Opções: apagar antes, comprimir (`-z`), verificar após gravar.

## Requisitos
- Linux (testado em Linux Mint & Debian 13).
- Python 3
- python3-tk
- python3-venv
- Acesso à porta serial (grupo dialout)

## Instalação

### Opção 1 — Pacote `.deb` (recomendado)

Baixe o arquivo `.deb` mais recente na aba
[Releases](https://github.com/Jpreinehr/GravaBin/releases) — não é necessário
clonar o repositório inteiro — e instale com:

```bash
sudo apt install ./gravabin_*_amd64.deb
```

O pacote resolve suas dependências Python automaticamente (cria um venv em
`/usr/lib/gravabin/.venv` na pós-instalação) e adiciona um atalho no menu de
aplicativos. Depois de instalado, execute com:

```bash
gravabin
```

Para remover: `sudo apt remove gravabin`.

### Opção 2 — A partir do código-fonte

```bash
git clone https://github.com/Jpreinehr/GravaBin.git
cd GravaBin
chmod +x install.sh run.sh
./install.sh
```

O instalador cria um `.venv` local, instala `esptool` + `pyserial`, e adiciona
seu usuário ao grupo `dialout` (faça logout/login depois disso para acessar
`/dev/ttyUSB*` sem `sudo`).

## Uso

```bash
./run.sh
```

Exemplo de gravação ESP32 Arduino:

| Offset     | Arquivo                |
|------------|------------------------|
| `0x1000`   | `bootloader_qio_80m.bin` |
| `0x8000`   | `partitions.bin`       |
| `0xe000`   | `boot_app0.bin`        |
| `0x10000`  | `app.ino.bin`          |
| `0x3D0000` | `spiffs.bin` (opcional)|

Ao abrir, escolha o modo na tela inicial (o botão **Trocar modo** volta para
ela). No modo de **gravação única**, marque os checkboxes desejados, escolha
porta/baud e clique em **Gravar**.

### Presets

- A aba **Padrão** existe sempre e não pode ser renomeada nem removida.
- **Novo preset**: cria uma nova aba já com os offsets típicos.
- **Salvar preset**: pede um nome e grava a aba atual em disco.
- **Excluir preset**: remove a aba atual (exceto a Padrão).
- **Duplo clique na aba**: renomeia (salvando).
- **Exportar…**: gera um arquivo `.gravabin` com o preset da aba atual —
  offsets, configurações (chip, baud, flash mode/freq/size, apagar, comprimir,
  verificar) **e os próprios binários**. Envie esse arquivo aos colegas.
- **Importar…**: abre um `.gravabin` como uma nova aba. Os binários são
  extraídos em `~/.local/share/gravabin/presets/<nome>/`, então o preset já
  funciona sem ajustar caminhos. Se o nome já existir, vira `Nome (2)`.

As configurações de gravação (chip, baud, flash mode/freq/size e opções) são
de cada preset: ao trocar de aba, os campos mudam junto. Presets criados em
versões anteriores herdam as configurações que estiverem na tela.

Cada aba tem uma linha por binário típico do ESP (quantidade fixa); basta
marcar os checkboxes e escolher os arquivos. As abas são salvas automaticamente
ao fechar o programa e recarregadas na próxima abertura, permitindo transitar
entre padrões de gravação diferentes (ex.: um preset por modelo de placa).

### Gravação múltipla

Para gravar o mesmo firmware em várias placas de uma vez (ex.: linha de
produção com um hub USB):

1. Na tela inicial, escolha **Gravação múltipla**.
2. Escolha o **preset** (os presets são editados no modo de gravação única);
   as configurações dele são carregadas e podem ser ajustadas para esta sessão.
3. Marque as **portas** que serão usadas (**↻ Atualizar portas** após plugar
   as placas; **Marcar todas** / **Desmarcar todas**).
4. Clique em **Gravar selecionadas**. Cada porta roda seu próprio `esptool` em
   paralelo e mostra o andamento e o resultado (✔/✖); o console identifica cada
   linha com a porta (`[ttyUSB0] …`). **Parar** cancela todas.

Com muitas placas no mesmo hub, se houver falhas de conexão, reduza o baud.

### Modo compilador

Compila e carrega sketches `.ino` como o Arduino IDE 1.8.19, usando o
[arduino-cli](https://arduino.github.io/arduino-cli/) oficial que vem dentro
do pacote `.deb`. Não há editor embutido: edite o código no seu editor
preferido (o botão **Editar** abre o `.ino` no editor padrão do sistema).

1. **Gerenciar placas…**: instale o pacote **esp32:esp32** e/ou
   **esp8266:esp8266** (as URLs da Espressif e da comunidade ESP8266 já vêm
   configuradas; **URLs adicionais…** aceita outras). O ESP32 baixa cerca de
   1 GB de ferramentas na primeira vez.
2. **Abrir…** o `.ino` (a pasta precisa ter o mesmo nome do `.ino`, regra do
   Arduino), escolha a **placa** (digite para filtrar) e ajuste as **opções da
   placa** — os mesmos menus de *Ferramentas* do IDE (partição, PSRAM, CPU…).
3. **✔ Verificar** compila; **➜ Carregar** compila e grava na porta escolhida.
   Erros de compilação aparecem em vermelho no console.
4. **Salvar como preset…** transforma a última compilação em um preset de
   gravação (ESP32 core 3.x: `merged.bin` em `0x0`; ESP8266: `.bin` em `0x0`),
   pronto para a **gravação múltipla** ou para exportar aos colegas.

**Gerenciar bibliotecas…** busca e instala bibliotecas do índice oficial do
Arduino (com escolha de versão e dependências), instala a partir de `.zip` e
atualiza/remove as instaladas.

Placas, índices e bibliotecas ficam nas mesmas pastas do Arduino IDE 1.8
(`~/.arduino15` e `~/Arduino/libraries`, ou o sketchbook configurado no IDE):
o que for instalado em um aparece no outro. As URLs adicionais configuradas no
IDE também são usadas. Placa, opções, porta e último sketch são lembrados em
`~/.config/gravabin/compiler.json`.

### Monitor serial

Controles do monitor ficam na barra de botões de ação, ao lado de
**Ler MAC / Chip**:

- **Abrir monitor / Fechar monitor**: abre a porta selecionada e mostra tudo
  que o dispositivo enviar direto no console.
- **Baud monitor**: velocidade do monitor, independente do baud de gravação
  (padrão `115200`; `74880` é útil para o boot log do ESP8266).
- **Reabrir após gravar/apagar**: se o monitor estiver aberto quando você
  clicar em Gravar/Apagar/Ler MAC, ele é fechado automaticamente (a porta fica
  livre para o `esptool`) e reaberto quando a operação termina.
- **Data/hora nas linhas**: prefixa cada linha recebida com o instante de
  chegada (`[2026-11-04 14:03:21.123]`). Pode ser ligado/desligado com o
  monitor aberto.
- **Exportar log…**: salva em `.log`/`.txt` apenas a saída do monitor serial
  (sem as mensagens do `esptool`). **Limpar log** também limpa esse histórico.

O monitor é fechado sozinho ao sair do programa ou se o dispositivo for
desconectado.

## Atalho no menu

Ao instalar via `.deb` (Opção 1), o atalho já é criado automaticamente.

Rodando a partir do código-fonte (Opção 2), `gravabin.desktop` aponta para o
comando `gravabin` instalado pelo pacote — para usá-lo sem o `.deb`, ajuste a
linha `Exec=` para o caminho completo de `run.sh` antes de copiar:

```bash
sed "s#Exec=gravabin#Exec=$(pwd)/run.sh#" gravabin.desktop \
    > ~/.local/share/applications/gravabin.desktop
```

## Gerando o pacote `.deb` (desenvolvedores)

Quem for empacotar uma nova versão pode gerar o `.deb` localmente:

```bash
sudo apt install dpkg-dev librsvg2-bin curl
./build_deb.sh                    # arquitetura desta máquina
PKG_ARCH=arm64 ./build_deb.sh     # ou outra: amd64, arm64, armhf, i386
```

O pacote fica em `dist/gravabin_<versão>_<arquitetura>.deb`. Como ele embute o
binário nativo do arduino-cli, há um pacote por arquitetura. O script baixa a
versão fixada em `ARDUINO_CLI_VERSION` (com cache em `build/cache/`) e confere
o SHA-256 contra a lista oficial da release antes de empacotar.

O número de versão é definido em `PKG_VERSION` no início do script e deve
acompanhar `APP_VERSION` em `gravabin_app/constants.py`.

Rodando do código-fonte, o modo compilador usa um `arduino-cli` do `PATH` ou
o binário colocado em `bin/arduino-cli` no repositório.

## Solução de possíveis problemas

- **Permission denied em `/dev/ttyUSB0`**: faça logout/login após o
  `install.sh` ou rode `sudo usermod -a -G dialout $USER` manualmente.
- **`esptool` não encontrado**: ative o venv (`source .venv/bin/activate`) ou
  use sempre `./run.sh`.
- **Falha ao conectar (timed out waiting for packet)**: segure o botão `BOOT`
  do ESP enquanto pressiona `RESET`, depois solte; tente baud menor (115200).

## Sem garantia

Este programa e seu código-fonte são fornecidos "no estado em que se encontram",
sem garantias de qualquer tipo, expressas ou implícitas. O uso é por conta e
risco do usuário. O autor não se responsabiliza por perdas de dados, danos em
hardware, interrupções de serviço ou quaisquer outros prejuízos decorrentes do
uso deste software.

## Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo `LICENSE`.

## Contato

 E-mail: jpreinehr@gmail.com
 LinkedIn: (https://www.linkedin.com/in/joaoreinehr/)
