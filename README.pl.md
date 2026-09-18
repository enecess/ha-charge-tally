# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · **Polski** · [Italiano](README.it.md)

Rejestruj energię i koszty ładowania w Home Assistant według punktu i tożsamości oraz sprawdzaj rozliczenie każdego ładowania. Charge Tally korzysta z istniejących czujników energii lub mocy. Prowadzi rejestr, ale nie steruje włączaniem ładowarki.

- Jedna księga dla wielu punktów; pojazdy, kierowcy lub domownicy jako wspólne tożsamości.
- Energia skumulowana, energia obliczana z mocy albo pomiar energii z wykrywaniem na podstawie mocy.
- Ceny stałe, dynamiczne i dzienne taryfy czasowe, również zerowe i ujemne.
- Wykrywanie automatyczne lub rozpoczynanie i kończenie wpisów przez kartę i automatyzacje HA.
- Bieżące ładowanie, statystyki dzienne, miesięczne, roczne, całkowite i wybranego zakresu oraz wykresy dzienne.
- Dodawanie historii, edycja zakończonych wpisów, zmiana tożsamości, unieważnianie błędów oraz przegląd segmentów i wersji.
- Zarządzanie archiwalnymi punktami i tożsamościami oraz trwałe usuwanie zbędnych danych księgi.

Konfiguracją zarządza się przez **Ustawienia → Urządzenia oraz usługi → Charge Tally**. Karta **Charge Tally** w pulpicie służy do przeglądania i obsługi wpisów. Zawiera kilka obszarów na jednej stronie; szczegóły i edycja otwierają się w oknach dialogowych.

> Miejsce na zrzut ekranu 01: Cała karta z punktami, statystykami i listą wpisów.

## Nawigacja

- [Wymagania](#wymagania)
- [Instalacja integracji](#instalacja-integracji)
- [Pierwsza konfiguracja](#pierwsza-konfiguracja)
- [Tożsamości i późniejsze zmiany](#tożsamości-i-późniejsze-zmiany)
- [Dodawanie i ustawienia karty](#dodawanie-i-ustawienia-karty)
- [Obszary karty](#obszary-karty)
- [Codzienna obsługa wpisów](#codzienna-obsługa-wpisów)
- [Dodawanie i edycja historii](#dodawanie-i-edycja-historii)
- [Statystyki i jakość danych](#statystyki-i-jakość-danych)
- [Natywne encje i automatyzacje](#natywne-encje-i-automatyzacje)
- [Archiwum i waluta](#archiwum-i-waluta)
- [Aktualizacje, kopie i przywracanie](#aktualizacje-kopie-i-przywracanie)
- [Częste pytania](#częste-pytania)

## Wymagania

Potrzebujesz **Home Assistant 2025.3.4 lub nowszego**, przynajmniej jednego czujnika obwodu ładowania i konta administratora do instalacji oraz konfiguracji. Interfejs używa języka HA. Poniżej podano rzeczywiste polskie etykiety; położenie ogólnych menu może zależeć od wersji HA.

| Dostępny pomiar | „Tryb pomiaru energii” | Zastosowanie |
| --- | --- | --- |
| Energia skumulowana w Wh, kWh lub MWh | **Tylko energia** | Rozliczanie z licznika; rozpoczęcie i zakończenie przez kartę lub automatyzację |
| Moc w W lub kW | **Tylko moc (natywny Integral)** | Automatycznie tworzona encja pomocnicza HA oblicza energię; możliwe wykrywanie |
| Energia i moc | **Energia i moc** | Energia do pomiaru, moc do wykrywania; bez podwójnego liczenia |

Energia skumulowana oznacza zwykle rosnący stan licznika, ewentualnie rosnący ponownie po wyzerowaniu, a nie zużycie z ostatniej godziny. Czujniki powinny być oznaczone w HA jako energia lub moc i podawać prawidłowe, nieujemne wartości. Tego samego źródła nie można przypisać wielu punktom.

Dla cen dynamicznych przygotuj czujnik w walucie księgi. Przy odtwarzaniu historycznych wpisów HA musi rejestrować czujniki i nadal przechowywać potrzebny okres.

## Instalacja integracji

### Sposób 1: HACS

Jeśli nie masz HACS, zainstaluj go zgodnie z [oficjalną instrukcją](https://hacs.dev/docs/use/download/download/).

1. Otwórz **HACS**, następnie menu w prawym górnym rogu i **Niestandardowe repozytoria**.
2. Dodaj `https://github.com/enecess/ha-charge-tally` jako **Integracja**.
3. Wyszukaj **Charge Tally**, otwórz i pobierz wybraną wersję.
4. **Uruchom ponownie Home Assistant.**
5. Otwórz **Ustawienia → Urządzenia oraz usługi → Dodaj integrację** i wybierz **Charge Tally**.
6. Przejdź do pierwszej konfiguracji. Samo pobranie nie tworzy księgi ani punktu.

> Miejsce na zrzut ekranu 02: Repozytorium HACS, pobieranie i wyszukiwanie integracji.

### Sposób 2: Instalacja ręczna

1. Pobierz repozytorium, rozpakuj i znajdź `custom_components/charge_tally`.
2. Otwórz katalog konfiguracji HA zawierający `configuration.yaml`.
3. Utwórz w razie potrzeby `custom_components` i skopiuj do niego cały folder `charge_tally` wraz z podfolderami.
4. Sprawdź ścieżkę `custom_components/charge_tally/manifest.json`; nie dodawaj dodatkowego poziomu folderu repozytorium.
5. **Uruchom HA ponownie**, następnie wybierz **Ustawienia → Urządzenia oraz usługi → Dodaj integrację → Charge Tally**.

Karta jest dołączona do integracji i nie wymaga osobnego pobierania w HACS. Jeśli integracji nie widać, sprawdź strukturę folderów i restart, odśwież stronę oraz sprawdź dzienniki HA.

## Pierwsza konfiguracja

### 1. Utwórz księgę

W oknie **Rejestr Charge Tally** podaj **Waluta**, na przykład PLN, EUR lub USD. Każda instalacja HA ma jedną księgę; wszystkie punkty i wpisy używają tej samej waluty.

- Walutę można zmienić bez punktów, również archiwalnych, i bez zachowanych danych księgowych. Same tożsamości jej nie blokują.
- Dodanie punktu blokuje walutę nawet przed pierwszym ładowaniem.
- Usunięcie konfiguracji zachowuje historię; dopiero pełne usunięcie wszystkich punktów i powiązanych danych pozwala zmienić walutę.
- Nie ma przeliczania walut. Przy ponownym dodawaniu usuniętej integracji wybierz pierwotną walutę zachowanej księgi.

> Miejsce na zrzut ekranu 03: „Rejestr Charge Tally” z walutą i objaśnieniami.

### 2. Dodaj punkt ładowania

Wersje HA obsługujące bezpośrednią kontynuację otworzą następnie okno punktu. W przeciwnym razie przejdź do **Ustawienia → Urządzenia oraz usługi → Charge Tally → Dodaj punkt ładowania**.

W oknie **Punkt ładowania** wpisz **Nazwa**, na przykład „Garaż”, i wybierz **Tryb pomiaru energii**. Punkt oznacza osobno mierzony obwód ładowania.

### 3. Wybierz źródła pomiarów

W oknie **Źródła pomiarów** rozwiń **Pomiar i wykrywanie**:

| Pole | Co wybrać |
| --- | --- |
| **Czujnik skumulowanej energii** | Licznik tego obwodu; niewidoczny w trybie „Tylko moc (natywny Integral)” |
| **Czujnik mocy** | Moc obwodu; niewidoczny w trybie „Tylko energia” |
| **Licznik może się zerować** | Pozostaw włączone, jeśli możliwe jest zerowanie; spadek oznacza niekompletny przedział z resetem |
| **Maksymalny interwał przypisywania (sekundy)** | Domyślnie 600; dłuższe odstępy pomiarów są lukami wymagającymi sprawdzenia |
| **Automatyczne wykrywanie ładowania** | Tylko dla trybów z mocą; włączenie otwiera parametry wykrywania |

### 4. Ustaw wykrywanie automatyczne (opcjonalnie)

Po włączeniu **Automatyczne wykrywanie ładowania** otwiera się **Automatyczne wykrywanie**:

- **Próg rozpoczęcia (W)**: osiągnięcie lub przekroczenie rozpoczyna potwierdzanie startu.
- **Czas potwierdzenia rozpoczęcia (sekundy)**: po ciągłym spełnieniu warunku powstaje wpis; domyślnie 30 sekund.
- **Próg zakończenia (W)**: spadek poniżej rozpoczyna potwierdzanie końca; musi być niższy od progu rozpoczęcia.
- **Czas potwierdzenia zakończenia (sekundy)**: po ciągłym spełnieniu warunku wpis się kończy; domyślnie 300 sekund.

Dostosuj progi do rzeczywistej mocy czuwania i ładowania. Po potwierdzeniu czas wpisu jest cofany do początku spełnienia warunku. Krótsze przerwy pozostają częścią tego samego wpisu. Wybierz tożsamość przed wzrostem mocy, ponieważ zapamiętywana jest już przy rozpoczęciu potwierdzania.

Bez wykrywania nadal działają **Rozpocznij wpis** i **Zakończ wpis**.

> Miejsce na zrzut ekranu 04: Źródła pomiarów, wykrywanie i okno parametrów.

### 5. Skonfiguruj cenę

Opcje **Tryb ceny** i nazwy kolejnych okien częściowo się różnią:

| Opcja | Okno | Dane |
| --- | --- | --- |
| **Stała** | **Cena stała** | **Cena za kWh** w walucie księgi |
| **Czujnik dynamiczny** | **Cena dynamiczna** | **Czujnik ceny**, w razie potrzeby **Potwierdzona jednostka** |
| **Dzienna taryfa czasowa** | **Dzienny harmonogram taryf czasowych** | Przedziały cenowe całej doby |

Ceny stałe i czasowe mogą być zerowe lub ujemne. Dynamiczne obsługują walutę księgi za Wh, kWh lub MWh. Jednostki energii są przeliczane, waluty nie. **Potwierdzona jednostka** uzupełnia tylko brak jednostki i nie zastępuje istniejącej niezgodnej waluty lub jednostki.

W oknie **Dzienny harmonogram taryf czasowych**:

1. W polu **Działanie** wybierz **Dodaj przedział**.
2. W **Edytuj przedział cenowy** wypełnij **Godzina rozpoczęcia**, **Godzina zakończenia (24:00 = koniec doby)** i **Cena za kWh**.
3. Dodaj kolejne przedziały. Aby zmienić lub usunąć, wybierz **Przedział**, następnie **Edytuj przedział** lub **Usuń przedział**.
4. Gdy cała doba jest pokryta, wybierz **Zakończ harmonogram**.

Użyj `HH:MM`, np. `00:00–08:00`, `08:00–22:00`, `22:00–24:00`. Możliwy jest też przedział `22:00–06:00`. Bez luk, nakładania i jednakowych końców; cała doba to `00:00–24:00`. Plan powtarza się codziennie, bez rozróżnienia dni roboczych i weekendów.

> Miejsce na zrzut ekranu 05: Wybór ceny, jednostka dynamiczna, harmonogram i edycja przedziału.

### 6. Sprawdź statystyki okresowe i podsumowanie

W **Statystyki okresowe i podsumowanie** sprawdź nazwę, tryb pomiaru i ceny. W **Okresy statystyk energii** wybierz **Dzienne / Miesięczne / Roczne**. Domyślnie wybrane są wszystkie; można też nie wybrać żadnego.

Ustawienia tworzą dodatkowe natywne encje pomocnicze energii, nie decydują o dostępności statystyk wpisów lub tożsamości. Po zapisaniu sprawdź punkt na stronie integracji, poprawność czujników i brak komunikatów o naprawie.

> Miejsce na zrzut ekranu 06: Podsumowanie i skonfigurowana strona integracji.

## Tożsamości i późniejsze zmiany

W **Ustawienia → Urządzenia oraz usługi → Charge Tally** dostępne są:

| Wejście | Zastosowanie |
| --- | --- |
| **Dodaj punkt ładowania** | Kolejny niezależnie mierzony obwód |
| **Skonfiguruj punkt ładowania** | Nazwa, czujniki, wykrywanie, ceny i okresy statystyk |
| **Dodaj współdzieloną tożsamość** | Pojazd, osoba lub inny cel |
| **Skonfiguruj tożsamość** | Zmiana nazwy lub **Włączona** |
| **Konfiguruj** przy głównej integracji | **Ustawienia księgi** i **Zarządzaj danymi archiwalnymi** |

**Współdzielona tożsamość** zawiera tylko **Nazwa** i **Włączona**. Tożsamości są wspólne dla punktów; ich nazwy nie mogą powtarzać nazw innych skonfigurowanych tożsamości. Wbudowana **Unassigned** oznacza nieprzypisane wpisy i zachowuje tę angielską nazwę na liście wyboru.

Zmiana nazwy zachowuje przypisanie historii. Wyłączenie **Włączona** uniemożliwia nowe wybieranie tożsamości, ale zachowuje historię. Usunięcie konfiguracji również pozostawia historię; dopiero potem można trwale usunąć tożsamość przez archiwum. Wyłączenie i usunięcie konfiguracji to różne operacje.

Przed zmianą pomiaru lub wykrywania zakończ wpis i poczekaj, aż zakończy się **Potwierdzanie rozpoczęcia / Potwierdzanie zakończenia**. Zmiana ceny działa od chwili zmiany, bez przeliczania zapisanych kwot. Przed usunięciem punktu także zakończ wpis: usunięcie konfiguracji nie rozlicza automatycznie trwającego ładowania.

> Miejsce na zrzut ekranu 07: Tożsamość współdzielona i osobne wejścia konfiguracji.

## Dodawanie i ustawienia karty

1. Skonfiguruj przynajmniej jeden punkt i otwórz wybrany pulpit.
2. Włącz edycję. W układzie sekcji użyj plusa wewnątrz sekcji; w innych **Dodaj kartę**.
3. Wyszukaj typ karty **Charge Tally** i wybierz go.
4. Ustaw poniższe opcje w edytorze wizualnym, zapisz kartę i zakończ edycję pulpitu.

| Pole edytora | Działanie |
| --- | --- |
| **Tytuł** | Własny tytuł; puste wyświetla Charge Tally |
| **Punkt ładowania** | Początkowo wybrany punkt lub **Wszystkie** |
| **Filtr tożsamości** | Początkowo wybrana tożsamość lub **Wszystkie** |
| **Pokaż wpisy** | Pokazuje/ukrywa listę i przycisk dodawania historii |
| **Pokaż wykres** | Pokazuje/ukrywa wykres słupkowy; wartości statystyk pozostają |

Można umieścić kilka kart dla różnych punktów lub tożsamości. Są to filtry widoku, nie uprawnienia; użytkownik widzi wyłącznie dane dozwolone przez HA. Karta obsługuje polski, angielski, chiński uproszczony, niemiecki, francuski i włoski oraz dostosowuje się do motywu.

> Miejsce na zrzut ekranu 08: Dodawanie karty i pięć opcji edytora.

### Karty nie ma na liście

Sprawdź, czy integracja jest załadowana, i odśwież przeglądarkę. Przy zasobach pulpitu zarządzanych w interfejsie integracja zwykle rejestruje kartę automatycznie.

Jeśli potrzebna jest rejestracja ręczna, w menu **Ustawienia → Pulpity** otwórz **Zasoby**. Jeśli nie ma tej opcji, włącz **Tryb zaawansowany** w profilu. Dodaj poniższy zasób i odśwież:

| Pole | Wartość |
| --- | --- |
| URL | `/charge_tally/charge-tally-card.js?v=0.1.2-3` |
| Typ zasobu | **Moduł JavaScript** |

Istniejący zasób z tą samą ścieżką zaktualizuj, zamiast dodawać duplikat. Przy zarządzaniu zasobami w YAML wpisz tam tę samą ścieżkę i typ modułu. Nie instaluj drugiej kopii karty. Zobacz [dokumentację pulpitów HA](https://www.home-assistant.io/dashboards/dashboards/).

## Obszary karty

### Połączenie i filtry u góry

Obok tytułu widnieje **Połączono** albo **Rozłączono · oczekiwanie na aktualne dane**. Po powrocie połączenia można użyć **Spróbuj ponownie**. Stare wartości po rozłączeniu nie są aktualnym wynikiem rozliczenia.

**Punkt ładowania** i **Filtr tożsamości** dotyczą statystyk i listy. Wybór punktu określa też widoczne panele bieżące; filtr tożsamości nie zmienia tożsamości wybranej w punkcie. Zachowane obiekty historyczne mogą mieć oznaczenie **Zarchiwizowane**. Archiwalne punkty udostępniają historię, lecz nie panel rozpoczynania ładowania. Wyłączone tożsamości także mogą mieć to oznaczenie; możliwość trwałego usunięcia określa zarządzanie archiwum w integracji.

### Bieżący panel punktu

Każdy bieżący punkt pokazuje nazwę, stan, **Moc**, **Bieżąca cena** i **Wykrywanie**. Niedostępna moc lub cena może być pusta. **Wykrywanie** na karcie jest wskaźnikiem; zmieniaj je przez konfigurację punktu lub natywny przełącznik **Wykrywanie ładowania**.

| Element | Znaczenie |
| --- | --- |
| **Wybrana tożsamość** | Bez aktywnego wpisu: przypisanie następnego ładowania |
| **Ten wpis** | Tożsamość już przypisana do aktywnego wpisu |
| **Tożsamość następnego wpisu** | Przygotowanie kolejnego przypisania bez zmiany bieżącego |
| **Bieżący wpis · dane wstępne** | Energia, koszt, początek, czas trwania i jakość bieżącego wpisu |
| **Szczegóły** | Otwiera bieżący wpis |
| **Zmień tożsamość wpisu** | Koryguje bieżące przypisanie |
| **Rozpocznij wpis / Zakończ wpis** | Rejestruje początek lub koniec w bieżącej chwili |

> Miejsce na zrzut ekranu 09: Trwające ładowanie, bieżąca/następna tożsamość i wstępne koszty.

### Statystyki wpisów i wykres

W **Statystyki wpisów → Okres statystyk** wybierz **Dzisiaj / Ten miesiąc / Ten rok / Cały okres / Własny zakres**. Dla własnego zakresu podaj **Początek** i **Koniec (wyłącznie)**, następnie **Zastosuj zakres**. Cały 1 września oznacza początek 1 września, koniec 2 września.

Podsumowanie pokazuje **Energia**, **Koszt**, **Aktywne / zakończone** i jakość. **Odśwież** pobiera nowe wyniki. **Miara na wykresie** przełącza **Energia** i **Koszt** na wykresie dziennym. **Szczegóły** pod wykresem rozwijają tabelę wartości dziennych.

> Miejsce na zrzut ekranu 10: Statystyki, zakres dat, miara wykresu i tabela dzienna.

### Wpisy · wszystkie daty

Lista zawiera aktywne i zakończone wpisy, malejąco według początku, po 25 na stronę. **Poprzednia / Następna** zmienia stronę. Wiersz pokazuje punkt, tożsamość, początek, stan, energię, koszt i jakość; kliknięcie całego wiersza otwiera szczegóły.

Działają tylko filtry punktu i tożsamości: **Daty statystyk nie filtrują tej listy.** Przy „Dzisiaj” nadal widać stare wpisy. Obok tytułu jest **Dodaj wpis historyczny**; pusta lista pokazuje **Brak wpisów**.

> Miejsce na zrzut ekranu 11: Lista, dodawanie historii, wiersze i zmiana stron.

## Codzienna obsługa wpisów

### Ręczne rozpoczęcie i zakończenie

1. Wybierz w punkcie **Wybrana tożsamość**.
2. Kliknij **Rozpocznij wpis** i sprawdź **Bieżący wpis · dane wstępne**.
3. Na końcu kliknij **Zakończ wpis** i sprawdź wpis na liście.

Przyciski rejestrują czas i nie włączają ani nie wyłączają ładowarki. Wpis rozpoczęty ręcznie należy zakończyć ręcznie lub automatyzacją, nawet przy skonfigurowanym automatycznym wykrywaniu.

### Automatyczne wykrywanie ładowania

Możliwa sekwencja to **Potwierdzanie rozpoczęcia → Ładowanie → Potwierdzanie zakończenia → Brak aktywnego wpisu**. Gdy podczas potwierdzania warunek mocy przestaje być spełniony, kandydat jest anulowany; wpis może nie powstać lub się nie zakończyć.

Przed wstrzymaniem przez **Wykrywanie ładowania** zakończ aktywne wpisy i poczekaj na koniec potwierdzania. Jeśli nie ustawiono progów, uzupełnij je w **Skonfiguruj punkt ładowania**; sam przełącznik nie wystarczy. Po ręcznym zakończeniu moc musi najpierw spaść poniżej progu zakończenia, zanim wykrywanie rozpocznie następne ładowanie.

### Szczegóły i historia zmian

Szczegóły zawierają przypisanie, energię, koszt, czasy, strefę rozliczeń, **Stan**, **Źródło**, **Wersja**, notatkę i jakość.

- **Segmenty rozliczeniowe** pokazują czas, energię, koszt i **Jakość danych**, przydatne przy zmianie daty lub ceny.
- **Historia zmian** pokazuje tożsamość, stan, kwoty i notatkę każdej wersji. Nie ma przycisku cofającego do starej wersji.
- Aktywne wpisy pozwalają na **Zmień tożsamość wpisu**; tylko zakończone pokazują **Edytuj wpis** i **Unieważnij wpis**.

> Miejsce na zrzut ekranu 12: Zakończony wpis, segmenty, rozwinięta historia zmian i działania.

### Korekta tożsamości

Otwórz szczegóły i **Zmień tożsamość wpisu**, wybierz **Przypisana tożsamość**, następnie **Zapisz podgląd**. Tak rzeczywiście nazywa się przycisk zatwierdzenia tego okna; osobny podgląd zmian nie jest wymagany. Zmienia się przypisanie całego wpisu bez ponownego obliczania energii lub kwot.

### Unieważnienie błędnego wpisu

W zakończonym wpisie wybierz **Unieważnij wpis**, sprawdź i kliknij **Potwierdź unieważnienie**. Wpis znika ze statystyk i zwykłej listy, lecz oryginał i wersje pozostają w księdze. Nie ma widoku pokazującego unieważnione wpisy ani przycisku przywracania. Unieważnienie nie oznacza trwałego usunięcia.

## Dodawanie i edycja historii

**Dodaj wpis historyczny** otwiera **Nowy wpis historyczny**. Aby zmienić istniejący wpis, otwórz zakończony i wybierz **Edytuj wpis**.

1. Sprawdź **Strefa czasowa rozliczeń**, **Punkt ładowania** i **Przypisana tożsamość**. Nowe wpisy wymagają bieżącego punktu i włączonej tożsamości. Nawet gdy archiwalny punkt pojawia się na liście, nie można dodać do niego nowego wpisu. Przy edycji punkt jest stały.
2. Podaj datę i czas **Początek** oraz **Koniec (wyłącznie)**; koniec musi być późniejszy.
3. Podaj energię ręcznie lub pozostaw pustą i wybierz podstawę kosztu.
4. Opcjonalna **Notatka** ma maksymalnie 2000 znaków.
5. Kliknij **Podgląd zmian**. W **Podgląd · sprawdź przed zapisaniem** sprawdź kwoty, segmenty, jakość i **Pokrycie pomiarami**, a przy edycji także **Przed / Po**.
6. Bez nakładania wpisów kliknij **Zapisz podgląd**. Po zmianie formularza wygeneruj podgląd ponownie. **Zamknij** nie zapisuje.

| Pole lub opcja | Działanie |
| --- | --- |
| **Ręczna energia (kWh, puste: użyj historii)** przy dodawaniu | Puste próbuje użyć dostępnej historii; podana wartość jest energią całkowitą |
| **Ręczna energia (kWh, puste: zachowaj obecną podstawę)** przy edycji | Puste zachowuje podstawę i nie usuwa wcześniejszej ręcznej energii |
| **Podstawa obliczania kosztu → Użyj dostępnej historii i cen** | Domyślne przy dodawaniu; wymaga rzeczywiście dostępnych danych i cen |
| **Podstawa obliczania kosztu → Zachowaj obecną podstawę obliczania kosztu** | Domyślne przy edycji; zmiana notatki nie powoduje przypadkowego przeliczenia |
| **Podstawa obliczania kosztu → Ręczny koszt całkowity** | Włącza pole o tej samej nazwie; kwota może być zerowa lub ujemna |
| **Podstawa obliczania kosztu → Oczekujące** | Koszt jawnie nieznany, nie traktowany jako bezpłatny |

Wpisy tego samego punktu nie mogą nakładać się w czasie. Nakładanie w podglądzie blokuje zapis. Przy nieaktualnym podglądzie lub zmienionym wpisie odśwież i wygeneruj nowy podgląd.

Odtwarzanie historii zależy od danych zachowanych przez HA i księgę; nie ma gwarancji odtworzenia dowolnie starego okresu. Braki można uzupełnić z rachunku ładowarki. Ręczne sumy energii lub kosztów są rozdzielane w czasie; **Ręczne nadpisanie / Szacowane** opisuje tę podstawę obliczeń.

Czasy dotyczą pokazanej strefy rozliczeń, nie strefy przeglądarki. Przy powtórzeniu czasu lokalnego podczas zmiany czasu wybierz **Powtórzony czas lokalny: wybierz chwilę UTC**. Nieistniejące czasy lokalne nie są akceptowane.

> Miejsce na zrzut ekranu 13: Dodawanie/edycja historii, podstawa kosztu i podgląd z pokryciem pomiarami.

## Statystyki i jakość danych

| Wskazówka | Znaczenie |
| --- | --- |
| **Wstępne / Oczekuje na rozliczenie** | Wpis lub granice pomiaru nie są ostateczne; późniejsze odczyty mogą zmienić wynik |
| **znana suma częściowa · oczekuje na rozliczenie** | Znana część kosztu, nie pełny rachunek; nieznane nie oznacza zera |
| **Brak ceny / Nieznana cena** | Brak prawidłowej ceny; sprawdź walutę, jednostkę, dostępność i historię |
| **Brak danych o energii / Luka w obserwacjach** | Za mało danych lub zbyt długi odstęp; sprawdź i ewentualnie uzupełnij ręcznie |
| **Reset licznika** | Spadek odczytu powoduje niekompletność danego przedziału |
| **Ręczne nadpisanie / Szacowane** | Wartości ręczne lub podział w czasie, a nie ciągły rzeczywisty pomiar |

Energia jest dzielona między dni, miesiące i lata; ładowanie przez północ nie trafia całe do dnia rozpoczęcia. Historyczne wpisy zachowują swoją strefę rozliczeń. Liczba zakończonych wpisów jest przypisywana według czasu rozpoczęcia: wpis może wnosić energię do zakresu bez zwiększania liczby zakończonych wpisów w nim.

Karta i statystyki tożsamości sumują wyłącznie wpisy ładowania. Natywne statystyki energii mogą zawierać także czuwanie poza wpisami. Edycja aktualizuje księgę, nie natywną historię licznika HA. Wykresy kosztów pokazują znane kwoty; liczba widocznych miejsc dziesiętnych nie zmienia zapisanej precyzji.

## Natywne encje i automatyzacje

Dane są dostępne także na stronach encji HA, w innych kartach i automatyzacjach. Przykłady dla punktu „Garaż” i tożsamości „Auto rodzinne”:

| Widoczna encja | Zastosowanie |
| --- | --- |
| **Garaż Energia** | Skumulowana energia punktu |
| **Garaż Stan** | Stan ładowania lub dostępności |
| **Garaż Energia wpisu / Garaż Koszt wpisu** | Aktywny wpis; bez aktywnego wpisu brak bieżącej wartości, nie ostatni wpis |
| **Garaż Tożsamość** | Przypisanie następnego wpisu, np. przez RFID lub przycisk |
| **Garaż Wykrywanie ładowania** | Przełącznik wykrywania w trybach z mocą; nie przełącza zasilania |
| **Auto rodzinne Energia dzienna / Koszt dzienny, Energia miesięczna / Koszt miesięczny, Energia roczna / Koszt roczny, Energia całkowita / Koszt całkowity** | Statystyki tożsamości; odpowiednie encje ma też Unassigned |

Przy niepełnych kosztach natywna encja kosztu może nie mieć pełnej wartości, choć karta pokazuje znaną sumę częściową. Dodatkowe dzienne/miesięczne/roczne encje energii mają inne przeznaczenie niż statystyki tożsamości. Nie usuwaj ani nie zmieniaj ręcznie zarządzanych encji pomocniczych.

Wybór działań oferuje **Charge Tally: Rozpocznij rejestrowanie / Zakończ rejestrowanie / Zmień tożsamość przypisaną do wpisu**. Początek i koniec używają bieżącego czasu serwera; historyczne czasy uzupełnia się w karcie.

Wszystkie działania księgowe wymagają **ID żądania**, a zakończenie i zmiana przypisania także **Oczekiwana rewizja wpisu**. Sam wybór urządzenia nie wystarcza. Nowe operacje potrzebują różnych identyfikatorów; ponowienie tej samej zachowuje identyfikator i parametry. Do zmiany następnej tożsamości wystarczy **Garaż Tożsamość**. Jeśli nie chcesz obsługiwać pól weryfikacyjnych, rejestruj przez przyciski karty.

## Archiwum i waluta

### Usunięcie konfiguracji, unieważnienie i trwałe czyszczenie

| Operacja | Skutek |
| --- | --- |
| Wyłączenie tożsamości | Nie można jej wybierać dla nowych przypisań; konfiguracja i historia pozostają |
| Usunięcie konfiguracji punktu lub tożsamości | Historia pozostaje; obiekt może być zarządzany w archiwum. Wyłączenie nie jest usunięciem |
| Unieważnienie wpisu | Wykluczenie ze zwykłej listy i statystyk, zachowanie danych audytu |
| Trwała operacja w archiwum | Usunięcie obiektów księgi i danych powiązanych; brak cofnięcia w interfejsie |

### Trwałe usunięcie archiwalnego punktu

1. Przy głównej integracji otwórz **Konfiguruj → Zarządzaj danymi archiwalnymi → Archiwalne punkty ładowania**.
2. W **Wybierz obiekt archiwalny** wybierz punkt z usuniętą konfiguracją.
3. W **Potwierdź trwałą operację** sprawdź obiekt, operację, liczbę wpisów wraz z unieważnionymi, rewizje, zakres UTC, energię i znany koszt.
4. Zaznacz **Rozumiem skutki i potwierdzam trwałe usunięcie** i zatwierdź. **Operacja archiwum zakończona** pokaże liczbę usuniętych wpisów.

Usuwane są wpisy punktu, powiązane rewizje, próbki i historia cen z księgi. Nie jest to tylko ukrycie nazwy.

### Trwałe usunięcie archiwalnej tożsamości

Otwórz **Konfiguruj → Zarządzaj danymi archiwalnymi → Archiwalne tożsamości** i wybierz obiekt. Jeśli ma wpisy, najpierw w **Przenieś wpisy tożsamości** wybierz **Tożsamość docelowa**: istniejącą włączoną tożsamość albo **Unassigned**. Bez wpisów następuje bezpośrednio potwierdzenie.

Wszystkie wpisy, również unieważnione, są przenoszone bez zmiany kwot. Pierwotna tożsamość zostaje usunięta, a stare rewizje zachowują jej nazwę. Unassigned nie można usunąć. Używany obiekt lub zmiana danych w trakcie potwierdzania blokuje operację: zakończ aktywne wpisy lub otwórz podgląd ponownie.

Czyszczenie dotyczy tylko Charge Tally i **nie usuwa natywnej historii HA, statystyk długoterminowych ani kopii zapasowych**. Energia i znany koszt w potwierdzeniu obejmują wymienione unieważnione wpisy i opisują zakres operacji. Nie porównuj ich bezpośrednio ze zwykłymi statystykami pomijającymi te wpisy.

> Miejsce na zrzut ekranu 14: Kategorie archiwum, wybór obiektu, przeniesienie i potwierdzenie.

### Zmiana waluty

Przy głównej integracji otwórz **Konfiguruj → Ustawienia księgi**. Formularz zmiany pojawia się tylko bez punktów, również archiwalnych, i bez zachowanych danych księgowych. W przeciwnym razie **Waluta rejestru zablokowana** wyjaśnia przyczynę. Same tożsamości nie blokują waluty.

Aby zacząć od nowa w innej walucie, wykonaj potrzebną kopię, usuń nieużywane konfiguracje punktów, wyczyść ich dane archiwalne i ponownie otwórz ustawienia. To nowy wybór waluty po wyczyszczeniu, nie przeliczenie historycznych kwot.

## Aktualizacje, kopie i przywracanie

1. Przed aktualizacją wykonaj kopię obejmującą katalog konfiguracji HA.
2. Instalację HACS aktualizuj w HACS; ręczną przez wymianę całego folderu integracji z zachowaniem struktury.
3. Uruchom HA ponownie i odśwież pulpit w przeglądarce lub aplikacji. Przy własnym zarządzaniu zasobami sprawdź wersję podanego wyżej adresu.
4. Sprawdź punkty, wpisy i statystyki; wymagane naprawy przeprowadź przez interfejs napraw.

Księga znajduje się w katalogu konfiguracji HA. Podczas tworzenia kopii zapasowej Home Assistant przygotowywana jest spójna kopia księgi. Usunięcie integracji lub jej plików programu nie czyści aktywnie zachowanej księgi. Ponowne dodanie wymaga pierwotnej waluty. Przywracaj pasującą konfigurację i księgę razem, bez mieszania stanów z różnych okresów.

Lokalne obrazy marki są obsługiwane od **Home Assistant 2026.3**. Wyświetlanie ikon w starszych wersjach nie wpływa na rozliczanie.

## Częste pytania

| Problem | Co sprawdzić |
| --- | --- |
| Brak integracji po pobraniu | Czy zainstalowano integrację, katalog nie jest zagnieżdżony i wykonano restart? Szukaj przez „Dodaj integrację” |
| Brak karty | Załaduj integrację, odśwież interfejs, sprawdź adres zasobu i moduł JavaScript |
| **Brak dostępnych punktów ładowania. Skonfiguruj Charge Tally lub sprawdź uprawnienia.** | Zapewnij punkt i uprawnienia odczytu; same tożsamości nie tworzą panelu punktu |
| Brak automatycznych wpisów | Sprawdź źródło mocy, pełną konfigurację wykrywania, przełącznik, progi i czas potwierdzenia |
| „Rozpocznij wpis” niedostępne | Sprawdź źródło pomiaru, encję tożsamości i stan ładowania/naprawy integracji |
| Wybór tożsamości nie zmienia aktywnego wpisu | Wybór dotyczy następnego; użyj „Zmień tożsamość wpisu” dla istniejącego |
| Stare wpisy przy „Dzisiaj” | Daty statystyk nie filtrują „Wpisy · wszystkie daty” |
| Tylko znany koszt częściowy lub pusta encja kosztu | Sprawdź luki pomiarów, historię cen, walutę i jakość w szczegółach; nie oznacza to bezpłatnego ładowania |
| Nieaktualny podgląd, zmiana lub nakładanie wpisów | Odśwież, otwórz ponownie i wygeneruj podgląd; przy nakładaniu zmień czas, nie można ominąć kontroli |
| **Encje pomocnicze punktu ładowania wymagają naprawy** | Otwórz naprawę HA i potwierdź **Napraw zarządzane encje pomocnicze**; wadliwe własne encje są odtwarzane, historia pozostaje |
| Waluta zablokowana po usunięciu konfiguracji | Sprawdź punkty i dane księgowe w „Zarządzaj danymi archiwalnymi” |
| Zwykłe konto nie widzi archiwum lub nie może działać | Sprawdź prawa odczytu/sterowania HA, archiwum obsługuj jako administrator; filtry karty nie nadają uprawnień |

> Miejsce na zrzut ekranu 15: Powiadomienie o naprawie i „Napraw zarządzane encje pomocnicze”.

Potrzebujesz pomocy? [Zgłoś problem](https://github.com/enecess/ha-charge-tally/issues), podając wersje HA i Charge Tally, tryb pomiaru i ceny, kroki oraz rzeczywisty komunikat. Zasłoń prywatne dane na zrzutach.

[Licencja MIT](LICENSE)
