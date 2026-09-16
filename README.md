# GravaBin

**Versão 1.0.1**

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
- **Presets em abas** (estilo navegador): salve conjuntos de arquivos/offsets
  com um nome e alterne entre eles sem reselecionar tudo. Os presets ficam em
  `~/.config/gravabin/presets.json` e são restaurados ao abrir o programa.
- Configuração de baud, flash mode (`dio/qio/dout/qout`), freq, size.
- Botões para **Gravar**, **Apagar Flash** e **Ler MAC/Chip**.
- Console em tempo real com saída do `esptool`.
- **Monitor serial** embutido: acompanhe o que o firmware imprime na porta,
  com baud próprio e opção de reabrir o monitor automaticamente após
  gravar/apagar.
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
sudo dpkg -i gravabin_*_all.deb
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

Marque os checkboxes desejados, escolha porta/baud e clique em **Gravar**.

### Presets

- A aba **Padrão** existe sempre e não pode ser renomeada nem removida.
- **Novo preset**: cria uma nova aba já com os offsets típicos.
- **Salvar preset**: pede um nome e grava a aba atual em disco.
- **Excluir preset**: remove a aba atual (exceto a Padrão).
- **Duplo clique na aba**: renomeia (salvando).

Cada aba tem uma linha por binário típico do ESP (quantidade fixa); basta
marcar os checkboxes e escolher os arquivos. As abas são salvas automaticamente
ao fechar o programa e recarregadas na próxima abertura, permitindo transitar
entre padrões de gravação diferentes (ex.: um preset por modelo de placa).

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
sudo apt install dpkg-dev librsvg2-bin
./build_deb.sh
```

O pacote fica em `dist/gravabin_<versão>_all.deb`. O número de versão é
definido em `PKG_VERSION` no início do script e deve acompanhar `APP_VERSION`
em `gravabin.py`.

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
