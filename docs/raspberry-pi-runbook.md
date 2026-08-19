# Raspberry Pi -ajo-opas

Tämä on Jirai Sweeties -botin ensisijainen käyttöohje Raspberry Pi:n varmistamiseen, sammuttamiseen, uudelleenasentamiseen, palauttamiseen ja myöhempiin deployhin.

## 1. Ymmärrä missä data on

- Macin repo sisältää lähdekoodin, tuotantoconfigit ja palautetun paikallisen `data/`-hakemiston.
- Pi:llä ajavan `discord-bot`-kontin `/app/data` on aina ajantasaisen runtime-datan totuuden lähde.
- `/app/data` voi olla Dockerin nimetty volume tai hostin bind mount. Älä päättele lähdettä hakemiston nimestä; `backup_pi_data.sh` selvittää todellisen mountin Dockerilta.
- `discord_db.sqlite` sisältää Discord-käyttäjät.
- `store_db.sqlite` sisältää kaupat, tuotteet ja ilmoitustilan.
- SQLite voi pitää uusimmat kirjoitukset `-wal`- ja `-shm`-tiedostoissa. Älä koskaan kopioi vain käynnissä olevan botin `.sqlite`-päätiedostoa.

Uusi asennus käyttää repoon kirjattua bind mountia `./data:/app/data`. Backup- ja restore-skriptit toimivat myös vanhan nimetyn volumen kanssa.

## 2. Muuttujat Macin Terminaliin

Aja nämä repokansion Terminalissa. Korvaa `OMA_PI_KAYTTAJA` Imagerissa luomallasi käyttäjänimellä. Vaihda host-arvoksi Pi:n IP, jos `raspberrypi.local` ei löydy:

```bash
cd /Users/angelica/Documents/dev/projects-released/showcase/jirai_sweeties

export PI_HOST=raspberrypi.local
export PI_USER=OMA_PI_KAYTTAJA
export PI_DIR=programs/jirai_sweeties
export PI_TARGET="${PI_USER}@${PI_HOST}"
```

Pi:n nykyisen IP:n näkee Pi:n terminaalissa komennolla `hostname -I`. Macilta voi kokeilla myös `raspberrypi.local`-nimeä.

Testaa avainkirjautuminen ilman salasanakyselyä:

```bash
ssh -o BatchMode=yes "$PI_TARGET" 'hostname && uname -m'
```

Jos se ei toimi mutta salasanakirjautuminen toimii, asenna projektin julkinen avain kerran:

```bash
ssh-copy-id -i ~/.ssh/jirai-deploy.pub "$PI_TARGET"
```

## 3. Ota varmistus ennen sammuttamista tai uudelleenasennusta

Kun Pi jää vielä käyntiin varmistuksen jälkeen:

```bash
./scripts/backup_pi_data.sh --update-local
```

Kun Pi sammutetaan heti varmistuksen jälkeen:

```bash
./scripts/backup_pi_data.sh --update-local --leave-stopped
```

Skripti tekee seuraavat asiat tässä järjestyksessä:

1. tarkistaa SSH:n, kontin, mountin ja molemmat tietokannat;
2. muistaa kontin alkuperäisen käyntitilan;
3. pysäyttää botin, jotta SQLite-snapshot on konsistentti;
4. kopioi koko kontin `/app/data`-mountin Macille;
5. ajaa molemmille kannoille `PRAGMA integrity_check`;
6. kirjoittaa kaikkien kopioitujen tiedostojen SHA-256-tarkistussummat;
7. säilyttää vanhan paikallisen `data/`:n snapshotin sisällä;
8. vaihtaa tarkistetun Pi-datan paikalliseksi `data/`:ksi;
9. käynnistää kontin takaisin, ellei käytetty `--leave-stopped`-valintaa.

Onnistuneen ajon lopussa pitää näkyä:

```text
✓ SQLite integrity and checksums verified
✓ Local data now matches the verified Pi snapshot
✓ Pi data backup complete
```

Snapshot löytyy hakemistosta `backups/pi-data-YYYYMMDD-HHMMSS/`:

```text
remote-data/              Pi:ltä kopioitu tarkistettu data
local-data-before-update/ aiempi paikallinen data
SHA256SUMS                snapshotin tarkistussummat
```

Tarkista snapshot tarvittaessa uudelleen:

```bash
export SNAPSHOT=backups/pi-data-YYYYMMDD-HHMMSS

(cd "$SNAPSHOT" && shasum -a 256 -c SHA256SUMS)
sqlite3 "$SNAPSHOT/remote-data/discord_db.sqlite" 'PRAGMA integrity_check;'
sqlite3 "$SNAPSHOT/remote-data/store_db.sqlite" 'PRAGMA integrity_check;'
```

Kaikkien manifestirivien pitää olla `OK`, ja molempien SQLite-komentojen pitää tulostaa `ok`.

### Käsin tehtävä SSH-varamenetelmä

Käytä tätä vain, jos `backup_pi_data.sh` ei ole saatavilla. Seuraa järjestystä tarkasti ja käynnistä aiemmin käynnissä ollut kontti takaisin myös virheen jälkeen:

```bash
export MANUAL_ID="$(date +%Y%m%d-%H%M%S)"
export MANUAL_BACKUP="backups/pi-data-${MANUAL_ID}"
mkdir -p "$MANUAL_BACKUP/remote-data"

REMOTE_WAS_RUNNING="$(ssh "$PI_TARGET" \
  'docker inspect -f "{{.State.Running}}" discord-bot')"
[ "$REMOTE_WAS_RUNNING" != true ] || \
  ssh "$PI_TARGET" 'docker stop discord-bot >/dev/null'

ssh "$PI_TARGET" '
  IMAGE=$(docker inspect -f "{{.Config.Image}}" discord-bot)
  docker run --rm --volumes-from discord-bot:ro \
    --entrypoint tar "$IMAGE" -C /app/data -cf - .
' | tar -C "$MANUAL_BACKUP/remote-data" -xf -

sqlite3 "$MANUAL_BACKUP/remote-data/discord_db.sqlite" \
  'PRAGMA integrity_check;'
sqlite3 "$MANUAL_BACKUP/remote-data/store_db.sqlite" \
  'PRAGMA integrity_check;'

(cd "$MANUAL_BACKUP" && find remote-data -type f -exec shasum -a 256 {} \; \
  > SHA256SUMS)

[ "$REMOTE_WAS_RUNNING" != true ] || \
  ssh "$PI_TARGET" 'docker start discord-bot >/dev/null'
```

Molempien integrity-tulosten pitää olla `ok`. Jos kopiointi tai tarkistus epäonnistuu, älä käytä hakemistoa palautukseen; käynnistä kontti takaisin viimeisellä `docker start` -komennolla. Automaattinen skripti on turvallisempi, koska se poistaa keskeneräisen snapshotin ja palauttaa kontin tilan myös virhepolulla.

## 4. Tarkistuslista ennen vanhan asennuksen pyyhkimistä

Varmista Macilla:

```bash
for file in \
  .env \
  bot/config/settings.json \
  bot/config/welcome_messages.txt \
  store_data_extractor/config/stores.json \
  store_data_extractor/config/user_agents.txt \
  data/discord_db.sqlite \
  data/store_db.sqlite; do
  test -f "$file" || { echo "PUUTTUU: $file"; exit 1; }
done

sqlite3 data/discord_db.sqlite 'PRAGMA integrity_check;'
sqlite3 data/store_db.sqlite 'PRAGMA integrity_check;'
```

Lisäksi:

- säilytä vähintään yksi kokonainen `backups/pi-data-*`-snapshot;
- kopioi tärkeä snapshot mielellään myös ulkoiselle levylle;
- varmista, että Macin lähdekoodi ja omat keskeneräiset muutokset säilyvät;
- älä lisää `.env`:iä, configeja, `data/`:a tai `backups/`:a Gitiin.

Jos käytit `--leave-stopped`-valintaa ja tarkistukset onnistuivat, sammuta Pi hallitusti:

```bash
ssh -t "$PI_TARGET" 'sudo poweroff'
```

Odota aktiivisuusvalon rauhoittumista ennen virtajohdon irrottamista.

## 5. Asenna Raspberry Pi OS uudelleen

1. Avaa [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Valitse Pi-malli ja **64-bittinen Raspberry Pi OS Lite**.
3. Aseta Imagerin mukautuksissa:
   - hostname, esimerkiksi `raspberrypi`;
   - oma käyttäjänimi; käytä samaa nimeä myöhemmin `PI_USER`-arvona;
   - aikavyöhyke ja näppäimistö;
   - tarvittaessa Wi-Fi;
   - SSH päälle ja mieluiten nykyinen julkinen SSH-avain.
4. Kirjoita ja varmista microSD-kortti Imagerilla.
5. Kytke Ethernet-kaapeli ennen ensimmäistä käynnistystä ja käynnistä Pi.

Raspberry Pi:n virallinen headless-ohje on [Getting started -dokumentaatiossa](https://www.raspberrypi.com/documentation/computers/getting-started.html#headless-setup).

Kun Pi vastaa, tarkista Macilta:

```bash
ssh "$PI_TARGET" 'hostname; hostname -I; uname -m'
```

`uname -m`-tuloksen pitää olla `aarch64`. Jos SSH varoittaa muuttuneesta host key -avaimesta heti itse tekemäsi uudelleenasennuksen jälkeen, poista vain vanhan oman Pi:n merkintä ja yhdistä uudelleen:

```bash
ssh-keygen -R "$PI_HOST"
ssh-keygen -R raspberrypi.local
ssh "$PI_TARGET"
```

Älä ohita host key -varoitusta, ellet varmasti tiedä osoitteen kuuluvan juuri uudelleenasennetulle Pi:lle.

Jos IP tai käyttäjänimi muuttui, päivitä tämän Terminal-istunnon `PI_HOST`, `PI_USER` ja `PI_TARGET` ennen seuraavia vaiheita.

## 6. Asenna Docker Pi:lle

Raspberry Pi OS 64-bit käyttää Debianin `arm64`-paketteja. Aja Pi:n SSH-istunnossa [Dockerin virallisen Debian-ohjeen](https://docs.docker.com/engine/install/debian/) mukaisesti:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

[Docker-ryhmä antaa käyttäjälle root-tasoiset oikeudet](https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user). Katkaise Pi:n SSH-istunto, jotta ryhmäjäsenyys voi päivittyä:

```bash
exit
```

Palaa Macin Terminaliin ja yhdistä uudelleen:

```bash
ssh "$PI_TARGET" 'docker version && docker compose version'
```

## 7. Rakenna ja siirrä sovellus uudelle Pi:lle

Aja Macin repokansiossa. Docker-image sisältää Gitistä pois jätetyt tuotantoconfigit; `.env` siirretään erikseen:

```bash
docker buildx build --platform linux/arm64 \
  -t discord-bot:latest --load .

docker save discord-bot:latest | gzip > /tmp/jirai-discord-bot.tar.gz

ssh "$PI_TARGET" "mkdir -p ~/$PI_DIR/data"
scp /tmp/jirai-discord-bot.tar.gz docker-compose.yml .env \
  "$PI_TARGET:~/$PI_DIR/"
```

Lataa image ja luo kontti **käynnistämättä sitä**:

```bash
ssh "$PI_TARGET" "
  set -eu
  cd ~/$PI_DIR
  chmod 600 .env
  gunzip -f jirai-discord-bot.tar.gz
  docker image load -i jirai-discord-bot.tar
  rm -f jirai-discord-bot.tar
  mkdir -p data
  APP_UID=\$(docker run --rm --entrypoint id discord-bot:latest -u)
  APP_GID=\$(docker run --rm --entrypoint id discord-bot:latest -g)
  sudo chown \"\$APP_UID:\$APP_GID\" data
  sudo chmod 700 data
  docker compose create --no-build --pull never discord-bot
  test \"\$(docker inspect -f '{{.State.Running}}' discord-bot)\" = false
"
```

Älä käynnistä bottia vielä: tietokannat palautetaan ensin.

## 8. Palauta tietokannat ja käynnistä botti

Valitse aiemmin tarkistettu snapshot ja aja Macilla:

```bash
export SNAPSHOT=backups/pi-data-YYYYMMDD-HHMMSS

./scripts/restore_pi_data.sh "$SNAPSHOT" --start
```

Restore-skripti:

- tarkistaa snapshotin SHA-256-manifestin ja SQLite-eheyden jo Macilla;
- vaatii kontin olevan pysäytetty;
- vaatii uuden `/app/data`-mountin olevan tyhjä eikä koskaan ylikirjoita olemassa olevaa dataa;
- siirtää snapshotin todelliseen Docker-mounttiin;
- tarkistaa molemmat kannat uudelleen Pi:llä;
- käynnistää botin vain onnistuneen tarkistuksen jälkeen.

Jos siirto katkeaa, skripti poistaa osittaisen datan ja jättää kontin pysäytetyksi.

## 9. Varmista palautettu tuotantoajo

```bash
ssh "$PI_TARGET" '
  docker ps --filter name=discord-bot
  docker inspect discord-bot --format \
    "{{range .Mounts}}{{println .Source \"->\" .Destination}}{{end}}"
  docker logs --tail 100 discord-bot
'
```

Tarkista:

- kontti näkyy `Up`-tilassa;
- mountin kohde on `/app/data`;
- lokissa näkyvät `Logged in as` ja `Database sync complete`;
- lokissa ei ole jatkuvia virheitä;
- vanhoja tuotteita ei lähetetä Discordiin uudelleen.

Uuden asennuksen bind mount tarkoittaa, että Pi:n ajantasaiset tiedostot näkyvät myös hakemistossa `~/programs/jirai_sweeties/data/`. Totuuden lähde tarkistetaan silti aina kontin mountista.

## 10. Normaali deploy myöhemmin

Repoon kirjattu deploy-skripti säilyttää molemmat tietokannat oletuksena ja ottaa ensin oikeasta Docker-mountista varmennetun off-device-snapshotin:

```bash
./scripts/deploy_pi.sh --keep-db --logs
```

Käytä `--replace-db`- tai `--fresh-db`-valintoja vain tietoisessa tietokantaoperaatiossa. Skripti ei koskaan vaihda legacy-nimettyä volumea bind mountiksi deployn sivuvaikutuksena, vaan vaatii silloin tämän oppaan backup/reinstall/restore-polun. Turvallinen normaali deploy on `--keep-db`, joka on myös skriptin oletus.

## 11. Pikainen vianrajaus

### Pi ei löydy

```bash
ping raspberrypi.local
```

Tarkista virta, Ethernet-kaapeli ja reitittimen DHCP-lista. Pi:n terminaalissa `hostname -I` näyttää osoitteet.

### SSH kysyy salasanaa

```bash
ssh-copy-id -i ~/.ssh/jirai-deploy.pub "$PI_TARGET"
ssh -o BatchMode=yes "$PI_TARGET" 'echo ok'
```

### Backup löytää vain yhden kannan

Älä kopioi hostin `data/`-hakemistoa käsin. Tarkista todellinen mount:

```bash
ssh "$PI_TARGET" 'docker inspect discord-bot --format \
  "{{range .Mounts}}{{println .Type .Source \"->\" .Destination}}{{end}}"'
```

### Restore sanoo, ettei `/app/data` ole tyhjä

Älä pakota ylikirjoitusta. Ota nykyisestä datasta ensin backup ja luo sen jälkeen uusi tyhjä kontti/mount ennen restore-komennon uusimista.
