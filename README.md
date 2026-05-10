# AnberMon

![CI](https://github.com/karolfurtak/AnberMon/actions/workflows/ci.yml/badge.svg)

Lekki **monitor systemu** dla **Anbernic RG40XX V** — pokazuje na żywo CPU, RAM, swap, temperaturę CPU, baterię, uptime + **wykres czasowy** (CPU/RAM/Temp z 4-minutowej historii). Sterowany D-padem, z możliwością wygaszenia ekranu przyciskiem POWER bez wyłączenia aplikacji.

![AnberMon screenshot](screenshot.png)

Opcjonalnie integruje się z [AnbernBot](https://github.com/karolfurtak/AnbernBot) — wyświetla stan bota Discord (online/offline, kolejka, aktywne zadania, ostatnie wiadomości i pliki).

## Features

- **Sekcja SYSTEM:** CPU%, RAM% (+ MB used/total), Swap%, Temp °C, bateria (% + status ładowania) — wszystko z paskami progresu i kodowaniem kolorystycznym (zielony/żółty/czerwony wg progów)
- **Sekcja BOT** *(opcjonalna):* status online/offline (psutil scan procesu `anberbot.py`), kolejka zadań, liczba plików w `/mnt/data/sprawozdania/`, uptime
- **Wykres czasowy** 640×100px: 3 linie (CPU zielona, RAM niebieska, Temp °C czerwona) na wspólnym układzie współrzędnych 0-100, siatka co 25%, 4 minuty historii (120 próbek × 2s)
- **Wiadomości Discord** *(z integracją AnbernBot):* ostatnie 12 wiadomości z kanałów / wątków
- **Ostatnie pliki** *(z integracją AnbernBot):* 3 ostatnio zapisane pliki sprawozdań
- **POWER button toggle ekranu** — naciśnij POWER raz: wygaszenie LCD przez `/sys/class/graphics/fb0/blank=4`, AnberMon dalej działa. Naciśnij ponownie: ekran wraca. Aplikacja co 200ms ponawia write — kernel nie zdąży przywrócić podświetlenia.
- **Atomic activity file** — bezpieczny odczyt JSON z bota, brak race condition
- Auto-restore ekranu na wyjściu

## Sterowanie

| Przycisk | Akcja |
|---|---|
| **MENU** (lub BTN_MODE) | Wyjście |
| **POWER** | Toggle ekran on/off (po 5s guard od startu) |
| **ESC** (BT klawiatura) | Wyjście |

Po starcie 5-sekundowy *guard period* — pierwsze klawisze ignorowane (zapobiega przypadkowemu wyjściu z dmenu).

## Wymagania

### Hardware

- **Anbernic RG40XX V** (Allwinner H700, axp2202 PMIC, 640×480 LCD landscape)
- inne RG40-serii **mogą działać** (kody przycisków evdev są zgodne z większością RG40xxx) — niesprawdzone

### Firmware

Tworzone i testowane na **stock Anbernic firmware build `20251225`**:
- Ubuntu 22.04.x LTS (Jammy)
- Kernel `4.9.170` (Allwinner H700 BSP)
- App Center: `dmenu.bin` (vendor)
- File: `/mnt/vendor/oem/version.ini` → `20251225`
- File: `/mnt/vendor/oem/board.ini` → `RG40xxV`

Inne firmware (muOS, Knulli, garlicOS) — niesprawdzone, mogą wymagać:
- innych kodów przycisków evdev (MENU może być inne niż 354)
- innej ścieżki do baterii (zamiast `axp2202-battery`)
- innej obsługi `fb0/blank` (POWER toggle może nie działać)

### System packages

Stock firmware już zawiera. Jeśli czegoś brakuje:
```bash
apt update
apt install python3 python3-pip libsdl2-2.0-0 fonts-dejavu
```

| Pakiet | Wersja stock | Rola |
|---|---|---|
| `libsdl2-2.0-0` | 2.0.20 | renderer SDL2 |
| `python3` | 3.10.x | runtime |
| `fonts-dejavu` (DejaVuSansMono.ttf) | systemowy | font UI |

### Python packages

| Pakiet | Wersja testowana | Rola |
|---|---|---|
| `pysdl2` | 0.9.17 | bindings do SDL2 |
| `evdev` | 1.6.1 | obsługa MENU/POWER (event0+event1) |
| `pillow` (PIL) | 12.2.0 | rysowanie do bufora |
| `psutil` | 7.2.2 | CPU/RAM/Swap + scan procesu bota |

Instalacja:
```bash
pip install pysdl2 evdev Pillow psutil
```

(Wszystkie zwykle są już obecne na stock firmware — `install.sh` sprawdza.)

## Instalacja

```bash
git clone https://github.com/karolfurtak/AnberMon.git
cd AnberMon
./scripts/install.sh
```

Skrypt:
- Kopiuje `app/main.py` do `/mnt/mmc/Roms/APPS/anbermon/main.py`
- Kopiuje launcher do `/mnt/mmc/Roms/APPS/AnberMon.sh`
- Generuje ikonę PNG (oscyloskop) do `/mnt/mmc/Roms/APPS/Imgs/AnberMon.png`

Po instalacji **AnberMon** pojawi się w App Center na konsoli.

## Architektura — co AnberMon faktycznie pokazuje

AnberMon jest **monitorem pipeline'u agenta**. Sam w sobie nie rozmawia z Discordem ani Claude Code — pokazuje **stan i przepływ danych** między tymi usługami które żyją na konsoli równolegle.

```
   ┌──────────────────┐         ┌────────────────────┐         ┌─────────────────┐
   │  Twój Discord    │ ◄────► │  Twój prywatny      │ ◄────► │  Claude Code    │
   │  serwer/kanały   │  text  │  bot Discord        │   PTY   │  (claude -p,    │
   │  + uploady       │  files │  (np. AnbernBot.py) │  stdin  │  Read/Bash/...) │
   └──────────────────┘         └─────────┬──────────┘         └─────────────────┘
                                          │
                                          ▼ pisze stan
                                ┌────────────────────┐
                                │ /mnt/data/         │
                                │ anberbot_activity  │
                                │ .json (atomic)     │
                                └─────────┬──────────┘
                                          │ czyta co 2s
                                          ▼
                                ┌────────────────────┐
                                │     AnberMon       │
                                │     (ten projekt)  │
                                └────────────────────┘
```

**Przepływ danych:**

1. Wysyłasz wiadomość lub plik na Discord (np. zdjęcie z laboratorium)
2. Twój bot Discord (działający na Anbernicu) odbiera ją przez Discord API
3. Bot zapisuje plik na `/mnt/data/sprawozdania/projekty/<kanał>/raw/`
4. Bot odpala `claude -p` w katalogu projektu — Claude Code czyta pliki, generuje sprawozdanie, zapisuje do `processed/`
5. Bot wraca z odpowiedzią na Discord
6. **W tym całym czasie** bot zapisuje co robi do `anberbot_activity.json` (kolejka, busy, ostatnie wiadomości i pliki)
7. AnberMon co 2 sekundy odczytuje ten plik i renderuje aktualny stan

**Bot Discord nie jest częścią tego repo** — jest Twój prywatny, dostosowany do Twojego workflow. AnberMon dostarcza tylko *kontrakt na plik aktywności* (patrz [Format pliku aktywności](#format-pliku-anberbotactivityjson) niżej) — jeśli Twój bot będzie do niego zapisywał w tym formacie, AnberMon pokaże dane.

> **Prywatność:** plik `anberbot_activity.json` zawiera nazwy Twoich kanałów Discord i fragmenty wiadomości. **Nigdy go nie commituj.** AnberMon tylko go czyta z dysku — niczego nie wysyła z urządzenia.

## Format pliku `anberbot_activity.json`

AnberMon czyta `/mnt/data/anberbot_activity.json` jako JSON o strukturze:

```jsonc
{
  "queue": 0,                  // liczba zadań w kolejce
  "busy": false,               // czy bot aktualnie przetwarza
  "messages": [                // ostatnie wiadomości (do 50 trzymanych przez bota, AnberMon pokazuje 12)
    {
      "time": "20:32:08",      // HH:MM:SS
      "channel": "test",       // nazwa kanału
      "thread": null,          // lub nazwa wątku
      "author": "ktoś",        // autor
      "content": "treść...",   // pierwsze 80 znaków
      "att": 0,                // liczba attachments
      "bot": false             // true = wiadomość bota, false = usera
    }
  ],
  "files": [                   // ostatnio zapisane pliki (do 20, AnberMon pokazuje 3)
    {
      "time": "20:31:51",
      "name": "raport.pdf",
      "project": "lab-3",      // nazwa projektu/kanału
      "size": 102400           // bajty
    }
  ]
}
```

Twój bot Discord aktualizuje ten plik przy każdej zmianie stanu. Zapis powinien być **atomowy** (`tmp + rename`) żeby AnberMon nie odczytał uszkodzonego JSON podczas write'a.

Plik powinien też wskazywać że bot żyje — AnberMon dodatkowo skanuje `psutil.process_iter()` w poszukiwaniu procesu o ścieżce zawierającej `anberbot` i na tej podstawie ustawia wskaźnik **online/offline**. Dostosuj nazwę procesu lub edytuj `bot_online()` w `app/main.py` jeśli używasz innej nazwy.

## Synchronizacja Discord + Claude Code na Anbernicu

Jeśli budujesz własnego bota Discord który będzie współpracował z AnberMonem, oto jak skonfigurować obie usługi na konsoli **od zera**:

### Część 1 — Discord

#### Krok 1.1: Konto Discord
Załóż konto na **https://discord.com** jeśli nie masz. Konto darmowe wystarcza.

#### Krok 1.2: Utwórz serwer (lub użyj istniejącego)
- Otwórz aplikację/web Discord
- Lewa kolumna → przycisk **+** (Add a Server)
- **Create My Own** → **For me and my friends**
- Nadaj nazwę (np. "Mój bot Anbernic")
- Po utworzeniu masz serwer z domyślnym kanałem `#general`. Możesz tworzyć więcej kanałów `+` przy "TEXT CHANNELS".

> Ten serwer to "guild" w API Discorda. Bot będzie do niego dodany w Kroku 1.5.

#### Krok 1.3: Utwórz aplikację bota (developer portal)
- Wejdź na **https://discord.com/developers/applications**
- Zaloguj się (tym samym kontem co serwer)
- **New Application** (prawy górny róg) → nadaj nazwę aplikacji (np. "MójBotAnbernic") → **Create**

#### Krok 1.4: Konfiguracja bota
- W lewym menu nowej aplikacji wybierz **Bot**
- Sekcja **Privileged Gateway Intents**:
  - **Message Content Intent** → **WŁĄCZ** (bot musi czytać treść wiadomości)
  - Server Members + Presence — opcjonalne, dla prostego bota niepotrzebne
- Sekcja **Token**:
  - **Reset Token** → zatwierdź → **skopiuj token natychmiast** (pokazany raz, jak zgubisz musisz znowu reset)
  - To długi ciąg `MzM5...` — zachowaj go jak hasło, NIE wklejaj nigdzie publicznie

#### Krok 1.5: Zaproś bota na swój serwer
- W lewym menu wybierz **OAuth2** → **URL Generator**
- **Scopes**: zaznacz `bot` (i `applications.commands` jeśli chcesz slash commands)
- **Bot Permissions**: zaznacz minimalnie:
  - `Read Messages/View Channels`
  - `Send Messages`
  - `Read Message History`
  - `Add Reactions`
  - `Attach Files`
  - `Embed Links`
- Na dole skopiuj **Generated URL**
- Wklej URL do przeglądarki → wybierz swój serwer → **Authorize** → przejdź captcha
- Bot powinien dołączyć do serwera (zobaczysz go offline w prawej kolumnie)

#### Krok 1.6: Zapisz token na konsoli (Anbernic)
Połącz się z konsolą po SSH i zapisz token jako env var (root-only):
```bash
sudo tee /etc/anberbot.env >/dev/null <<EOF
DISCORD_TOKEN=tu_wklej_swoj_token_z_kroku_1.4
EOF
sudo chmod 600 /etc/anberbot.env
```

**Nigdy nie commituj** `/etc/anberbot.env`. `.gitignore` powinien blokować `*.env`.

Twój bot będzie używał `os.environ['DISCORD_TOKEN']` do zalogowania (typowy wzorzec dla discord.py). systemd unit dla bota powinien mieć `EnvironmentFile=/etc/anberbot.env`.

### Część 2 — Claude Code

Wymagana subskrypcja Anthropic — testowane z **Claude Max** (działa też z **Claude Pro** lub kluczem API).

#### Krok 2.1: Konto Anthropic + subskrypcja
- Załóż konto na **https://claude.ai** (jeśli nie masz)
- W ustawieniach konta: **Settings → Plans** → wybierz Pro/Max (lub utwórz API key w **API Console**)

#### Krok 2.2: Zainstaluj Node.js + Claude Code na konsoli
```bash
# Przez SSH na Anbernic
apt update && apt install -y nodejs npm

# Globalna instalacja Claude Code
npm install -g @anthropic-ai/claude-code

# Sprawdź
which claude          # /root/.local/bin/claude lub /usr/local/bin/claude
claude --version
```

#### Krok 2.3: Login OAuth (przez SSH, NIE z konsoli)
Logowanie wymaga otwarcia URL w przeglądarce. Najprościej:

```bash
# Przez SSH na konsoli — uruchom interaktywną sesję Claude
ssh root@<IP-anbernic>
claude
```

W sesji Claude wpisz:
```
/login
```

- Wybierz tryb logowania: **Claude Max account** (lub Pro / API key)
- Claude wyświetli długi URL `https://claude.ai/auth/...`
- **Otwórz ten URL na laptopie/telefonie** w przeglądarce
- Zaloguj się do swojego konta Anthropic
- Strona pokaże **kod autoryzacyjny** — skopiuj go
- **Wklej kod** w terminalu SSH gdzie czeka prompt → Enter
- Claude zapisze token OAuth w `/root/.claude/credentials.json`

#### Krok 2.4: Test
```bash
# Wyjdź z interaktywnej sesji Claude (Ctrl+C × 2)
echo "powiedz cześć" | claude -p
# Powinieneś dostać polską odpowiedź — login działa
```

#### Krok 2.5 (alternatywa): klucz API zamiast OAuth
Jeśli wolisz nie używać OAuth (np. brak Pro/Max, masz tylko API):
```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> /root/.bashrc
source /root/.bashrc
# Test:
claude --bare -p "test"
```

> Token Claude Code (OAuth) jest w `/root/.claude/credentials.json` — chroń ten plik, nie udostępniaj. Klucz API jest w `/root/.bashrc` jako env var.

### Część 3 — Test przepływu w AnberMon

Po skonfigurowaniu (Discord token w env + Claude Code zalogowany), gdy uruchomisz swojego bota oraz AnberMon:
- Sekcja **BOT** w AnberMon pokaże `Bot: online` (zielony)
- **Status** → `gotowy` lub `przetwarza...` w zależności od stanu
- **Kolejka** → liczba zadań w buforze
- **WIADOMOŚCI DISCORD** → ostatnie 12 wiadomości (Twoich i bota)
- **OSTATNIE PLIKI** → 3 ostatnie pliki które bot zapisał

Wyślij testową wiadomość na swój serwer Discord — w ciągu 2 sekund powinna pojawić się w AnberMon.

## Logi

- `/mnt/data/anbermon.log` — stdout/błędy launchera
- `/mnt/data/anbermon_debug.log` — eventy SDL/evdev przy starcie + wyjście

## Hardware tricks użyte w aplikacji

Z całej zabawy z stock firmware na RG40XX V wyłapane przydatne fakty:

- **MENU button = evdev code 354** (KEY_MENU), NIE 316 (BTN_MODE jak na większości gamepadów)
- **Bateria:** `/sys/class/power_supply/axp2202-battery/{capacity,status,voltage_now}`
- **Temperatura:** `/sys/class/thermal/thermal_zone0/temp`
- **Wygaszenie LCD podczas SDL active:** `echo 4 > /sys/class/graphics/fb0/blank` (jedyna ścieżka która faktycznie działa — `axp2202-battery/brightness` jest vendor-specific i nie steruje LCD)
- **POWER button:** event0 (`/dev/input/event0`, axp2202-pek), code 116 (KEY_POWER) — z `HandlePowerKey=ignore` w logind nie suspends systemu

## Licencja

MIT — patrz [LICENSE](LICENSE).

## Powiązane

- [Anbernet](https://github.com/karolfurtak/Anbernet) — manager WiFi
- [AnberCC](https://github.com/karolfurtak/AnberCC) — Claude Code SDL2 terminal
