# Contrato das telas de informação (fonte → Pico)

O Pico do SP103 pode mostrar no display as horas e o desgaste da agulha (nas entradas do toca-discos) e a qualidade
do Bluetooth (na entrada DAB). Ele não sabe de onde vêm esses dados: só conhece este contrato.

Desde 2026-11-07 o Pico não mostra mais artista e música, faixa e posição, tempo do lado nem o aviso de fim do lado
(`firmware/screens.py`). Os campos continuam no contrato e a fonte continua mandando: o Pico lê e ignora. Quem quiser
voltar a mostrar não precisa mudar o pacote. Quem fala este contrato é uma
**fonte**. A fonte de hoje é o `sp103-vu-relay`, que lê o groove-identity e o groove-catalog
(`relay/nowplaying.go`); outra fonte (Volumio, Home Assistant) só precisa mandar os mesmos pacotes.

Tudo vai por UDP, na porta **7091** da fonte, a mesma do VU (`docs/vu.md`).

## Pedido (Pico → fonte)

| Pacote | Bytes | O quê |
|---|---|---|
| `"SUB1"` | 4 | Só o VU (o formato antigo; continua valendo) |
| `"SUB2"` + máscara | 5 | Máscara: bit 0 = VU, bit 1 = telas |

O pedido vale 6 s; o Pico repete a cada 2 s. Sem pedido válido, a fonte não manda nada. Uma fonte que só tem as telas
ignora o bit 0, e uma que só tem o VU ignora o bit 1.

## Telas (fonte → Pico)

```
"NP" versão(1) flags  campo 0x1F campo 0x1F ... campo
```

- `versão` = 1. O Pico ignora pacotes de outra versão.
- `flags`: bit 0 = tocando agora (o Pico mostra a agulha quando o disco começa a tocar); bit 1 = o lado acabou
  (o Pico ignora). É o fato: a fonte o repete enquanto valer.
- Os campos vêm sempre nesta ordem, separados pelo byte 0x1F. **Campo vazio = não se sabe**: a tela que depende dele
  não aparece, e as outras continuam.
- Texto só em ASCII de `" "` a `"}"`, sem `"\"` (a ROM do display não tem acentos; nela `"\"` vira `"¥"` e `"~"` vira
  seta). A fonte tira os acentos (`ã` → `a`) e corta cada texto em 40 caracteres.
- Números são inteiros em decimal.

| # | Campo | Exemplo | Tela |
|---|---|---|---|
| 0 | artista | `Pink Floyd` | (ignorado) |
| 1 | música | `Time` | (ignorado) |
| 2 | faixa no disco | `A4` | (ignorado) |
| 3 | posição na faixa (s) | `161` | (ignorado) |
| 4 | duração da faixa (s) | `421` | (ignorado) |
| 5 | lado | `A` | (ignorado) |
| 6 | faixa no lado | `4` | (ignorado) |
| 7 | faixas no lado | `5` | (ignorado) |
| 8 | tempo até o fim do lado (s) | `608` | (ignorado) |
| 9 | horas da agulha | `312` | Stylus |
| 10 | desgaste da agulha (%) | `62` | Stylus |
| 11 | streaming tocando: `airplay` ou `bluetooth` (vazio = nenhum) | `bluetooth` | nome da entrada DAB, Bluetooth quality |
| 12 | codec do streaming | `SBC` | Bluetooth quality |
| 13 | sample rate (Hz) | `44100` | Bluetooth quality |
| 14 | bits por amostra | `16` | Bluetooth quality |
| 15 | bitrate (kbit/s) | `328` | Bluetooth quality |

Um pacote fica com uns 60 a 150 bytes. Campos a mais no fim são ignorados (para versões futuras com campos novos).

### Quando mandar

- Quando qualquer campo ou flag muda (faixa nova, lado acabou, agulha).
- A cada 5 s enquanto houver pedido, mesmo sem mudança.

As posições e o tempo do lado valem **no instante do envio**.

Sem pacote por 15 s, o Pico descarta os dados e volta à tela do amp.

## Fonte de hoje: sp103-vu-relay

| Campo | De onde vem |
|---|---|
| artista, música, faixa no disco, posição, duração | groove-identity `GET /status` → `playback` (`artist`, `title`, `track_position`, `position_ms`, `duration_ms`), a cada 1 s |
| lado, faixa no lado, tempo do lado | a letra da `track_position` e a lista de faixas do disco: `album_programme.release_source` / `release_id` → groove-catalog `GET /catalog/library/releases/{source}/{id}/edition` (`draft.tracklist`: `position`, `duration_ms`), uma vez por disco. Se a edição falhar, usa `.../tracks`, que só tem as faixas que já tocaram, e lê de novo na próxima vez |
| agulha | groove-catalog `GET /catalog/stylus` → `metrics.stylus_hours_total`, `metrics.wear_percent`, a cada 10 min; vazio se `active` for falso |
| streaming, codec, sample rate, bits, bitrate | o arquivo de transporte do groove-detector, `/tmp/groove-transport.json` (`source`, `active`, `codec`, `samplerate`, `bitdepth`, `bitrate`), a cada 1 s; vazio sem arquivo ou com `active` falso. O bitrate só existe no Bluetooth com SBC, AAC ou aptX |
| lado acabou | na última faixa do lado, a menos de 30 s do fim pela duração do catálogo, o identity abriu uma captura nova (`recognition.epoch` > `playback.epoch`: o listener viu a música acabar) ou parou (`playback.active` falso); vale até a próxima faixa ou 15 min |

Os endereços dos dois serviços e o arquivo são opções da ponte (`-identity`, `-catalog`, padrão `127.0.0.1`;
`-transport`, padrão `/tmp/groove-transport.json`).
