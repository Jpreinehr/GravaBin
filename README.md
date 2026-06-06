# GravaBin

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
- Tabela com até 5 binários (offset + arquivo `.bin`), com presets típicos.
- Configuração de baud, flash mode (`dio/qio/dout/qout`), freq, size.
- Botões para **Gravar**, **Apagar Flash** e **Ler MAC/Chip**.
- Console em tempo real com saída do `esptool`.
- Opções: apagar antes, comprimir (`-z`).

## Requisitos
- Linux (testado em Linux Mint & Debian 13).
- Python 3
- python3-tk
- python3-venv
- Acesso à porta serial (grupo dialout)

## Instalação

```bash
cd gravabin
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

## Atalho no menu

Para criar um item de atalho rápido:

```bash
cp gravabin.desktop ~/.local/share/applications/
```

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
