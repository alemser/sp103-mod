# Wi-Fi do Pico: configurar sem cabo e achar sem IP

O Pico guarda a rede de casa no `wifi.json` e é configurado pela rede Wi-Fi dele mesmo, sem cabo USB. A app acha o Pico
na rede sozinha, sem IP digitado. O programa fica em `firmware/wifi.py`; os testes, em `tools/test_wifi.py`.

Decidido em 2026-11-08, depois de testar na bancada as duas formas:

- **Bluetooth, como o Oceano: descartado.** O Android pede o pareamento, mas ele nunca termina: o MicroPython oficial
  do Pico 2 W vem com o pareamento desligado (`MICROPY_PY_BLUETOOTH_ENABLE_PAIRING_BONDING = 0`). Sem pareamento, a
  senha do Wi-Fi passaria aberta pelo ar.
- **A rede própria do Pico: escolhida.** Funciona com o MicroPython oficial e com o Wi-Fi que o Pico já usa.

## Como funciona

1. **Sem rede salva**, o Pico abre na hora a rede de configuração **`AmpLink-SP103-XXXX`** (XXXX = o fim do endereço
   do chip). A senha é **`amplink-setup`**, a mesma em todos os Picos; a app conhece. Toda rede de configuração começa
   com `AmpLink-` (o MR 780 vai abrir `AmpLink-MR780-XXXX`): a app pede ao Android uma rede com esse começo, sem
   precisar da permissão de localização para procurar redes.
2. **Com rede salva que não conecta** (senha do roteador trocada, roteador desligado), o Pico continua tentando a cada
   30 s e, depois de 2 minutos sem conseguir, abre também a rede de configuração.
3. Quem entra na rede de configuração (a app, ou o navegador do celular em `http://192.168.4.1/`) escolhe a rede e
   manda a senha. O Pico conecta **sem fechar a rede de configuração**, para quem configurou ler o IP, e fecha 60 s
   depois. Se a rede nova falhar, ele volta para a anterior e diz o motivo.
4. **Trocar de rede com o Pico conectado:** `POST /wifi/setup` abre a rede de configuração por 10 minutos, sem largar a
   rede de casa.
5. **Achar o Pico:** a app manda `AMPLINK?` por broadcast UDP, porta **47800**, e o Pico responde
   `{"name": "SP103-D85E", "model": "sp103", "ip": "192.168.1.77"}`. Mandar umas 3 vezes em 2 s: o primeiro pacote às
   vezes se perde.

A rede de configuração só fica aberta quando o Pico está sem Wi-Fi (ou por 10 minutos, quando pedido). Uma senha fixa
basta para isso: quem entra nela só consegue trocar a rede do Pico.

## Rotas

| Rota | O quê |
|---|---|
| `GET /wifi` | `{"state", "detail", "ip", "ssid", "setup": {"open", "ssid"}}`. `state` e `detail` são a última tentativa: `idle`, `connecting`, `connected`, ou `failed` com o motivo (`wrong password`, `network not found`, `connection failed`, `timeout`). `ip` é o endereço de agora na rede de casa; `ssid`, a rede salva |
| `GET /wifi/networks` | As redes que o Pico vê: `[{"ssid", "rssi", "secure"}]`, uma por nome, da mais forte para a mais fraca, até 20. Leva ~1 s |
| `PUT /wifi` | `{"ssid": "Casa", "psk": "..."}` (sem `psk`, ou vazio = rede aberta; senão de 8 a 63 caracteres). Responde `202` na hora; o resultado sai no `GET /wifi`. **Só com a rede de configuração aberta**, senão `403` |
| `POST /wifi/setup` | Abre a rede de configuração por 10 minutos |
| `DELETE /wifi` | Esquece a rede salva. Só com a rede de configuração aberta |
| `GET /` | A página de configuração (escolher a rede e digitar a senha), só com a rede de configuração aberta. Fora disso, o Pico continua sem página web |

As rotas também respondem pela rede de casa: a app pode ler o `GET /wifi` a qualquer momento.

## Picos instalados antes desta versão

Sem `wifi.json`, o Pico usa o `WIFI_SSID` e o `WIFI_PASSWORD` do `secrets.py`, como antes. Na primeira configuração
pela rede própria, o `wifi.json` passa a valer, e essas duas linhas do `secrets.py` podem sair (pelo cabo, quando for
conveniente). O `UPDATE_PASSWORD` continua no `secrets.py`.

O `wifi.json` não é um `.py`: a atualização pelo Wi-Fi (`atualizacao-wifi.md`) nunca o envia, apaga ou devolve.

## Detalhes do Pico encontrados na bancada

- No `WLAN.scan()` do MicroPython para o Pico, o 6º campo é uma contagem (sempre 1 ou mais), não "rede oculta". A rede
  oculta aparece só com o nome vazio.
- O scan funciona com a rede de configuração aberta.
- O corpo de um pedido precisa ser lido antes da resposta: se o Pico fecha a conexão com bytes não lidos, o cliente
  perde a resposta.
- Redes com página de login ou com usuário (hotel, empresa) não funcionam: o Pico não tem como preencher.
