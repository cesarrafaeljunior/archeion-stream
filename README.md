# crflix

Servidor Jellyfin executado por Docker Compose, com a configuracao no projeto e
a midia armazenada localmente ou em um HD externo.

## Arquitetura de armazenamento

O container enxerga duas origens somente para leitura:

- `./media` no host vira `/media` no container;
- o caminho `MEDIA_ROOT` de `infra/jellyfin/.env` vira `/media-hd`.

As bibliotecas do Jellyfin usam `/media/series` e `/media-hd/series` para series,
`/media/animes` e `/media-hd/animes` para animes, e `/media/filmes` e
`/media-hd/filmes` para filmes. Nunca cadastre cada titulo como uma biblioteca
separada.

Use um ponto de montagem estavel para o HD, preferencialmente `/mnt/crflix`,
montado pelo UUID do volume. Caminhos automaticos como `/media/usuario/Ventoy1`
podem mudar a cada reconexao. O compose exige `MEDIA_ROOT`; assim ele nao inicia
por engano sobre um diretorio vazio quando a configuracao estiver ausente.

Estrutura esperada no HD:

```text
crflix/
├── animes/
│   └── Nome do Anime (2019)/
│       ├── Season 01/
│       │   └── Nome do Anime (2019) - S01E01 - Titulo.mkv
│       └── Season 02/
│           └── Nome do Anime (2019) - S02E01 - Titulo.mkv
├── filmes/
│   └── Nome do Filme (2024)/
│       └── Nome do Filme (2024).mkv
└── series/
    └── Nome da Serie (2020)/
        ├── Season 00/
        │   └── Nome da Serie (2020) - S00E01 - Especial.mkv
        ├── Season 01/
        │   ├── Nome da Serie (2020) - S01E01 - Titulo.mkv
        │   ├── Nome da Serie (2020) - S01E01 - Titulo.pt-BR.srt
        │   └── Nome da Serie (2020) - S01E02 - Titulo.mkv
        └── Season 02/
            └── Nome da Serie (2020) - S02E01 - Titulo.mkv
```

### Regras para adicionar series e episodios

1. Crie uma unica pasta por serie no formato `Nome da Serie (Ano)`.
2. Dentro dela, crie uma pasta por temporada: `Season 01`, `Season 02` etc.
   Use `Season 00` somente para especiais.
3. Todo episodio precisa conter `SxxEyy` no nome. O restante do nome e opcional,
   mas manter serie, ano e titulo reduz identificacoes ambiguas.
4. Coloque a legenda ao lado do video, com exatamente o mesmo nome-base e o
   idioma antes da extensao, por exemplo `...S01E03.pt-BR.srt`.
5. Nao deixe trailers publicitarios, arquivos `.url`, textos ou uma pasta
   generica `Legendas` dentro da temporada. O Jellyfin pode interpreta-los como
   itens de midia ou deixar de associar as legendas.
6. Para episodios duplos use `S01E01-E02`. Para varias versoes do mesmo episodio,
   siga a convencao de versoes do Jellyfin em vez de duplicar o numero.
7. Depois de copiar, execute uma varredura da biblioteca `Series` no painel do
   Jellyfin. Se o HD foi reconectado, recrie o container antes da varredura.

## Montagem e inicializacao

Copie `infra/jellyfin/.env.example` para `infra/jellyfin/.env`, informe `PUID`,
`PGID`, o caminho real de `MEDIA_ROOT` e o `MEDIA_UUID` do HD, e execute:

```bash
docker compose -f infra/jellyfin/docker-compose.yml up -d --force-recreate
```

Antes de iniciar, confirme que `MEDIA_ROOT/series` existe e contem os arquivos.
Em NTFS, ejete o HD corretamente. Se o kernel reportar `volume is dirty`, execute
`chkdsk /f` no Windows; montar com `force` pode agravar uma inconsistencia.

### Conectar e desconectar o HD com seguranca

Inicie o Jellyfin por meio do script de protecao. Ele recusa iniciar se o HD nao
estiver realmente montado ou se a estrutura esperada estiver ausente:

```bash
./infra/jellyfin/start.sh
```

Antes de retirar o cabo USB, sempre execute:

```bash
./infra/jellyfin/eject-hd.sh
```

Esse comando para o Jellyfin, descarrega o cache de escrita, desmonta a particao
e desliga logicamente o dispositivo. So remova o cabo depois da mensagem de
sucesso. Nao retire o HD se `udisksctl unmount` reportar que ele esta ocupado.

No Windows, use **Ejetar/Remover hardware com seguranca** antes de retirar o
cabo. Desative tambem **Inicializacao Rapida** em Opcoes de Energia; esse recurso
pode deixar volumes NTFS em estado de hibernacao mesmo depois de "Desligar".

Se o NTFS ja estiver marcado como inconsistente, conecte-o ao Windows e execute
em um terminal de administrador, substituindo `X:` pela letra correta:

```powershell
chkdsk X: /f
powercfg /h off
```

O segundo comando desativa hibernacao e Inicializacao Rapida. Depois reinicie o
Windows, ejete o HD pela bandeja do sistema e reconecte-o ao Linux. Nao use a
opcao de montagem `force` para contornar o reparo.
