# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · **Polski**

Śledź energię i koszty ładowania w Home Assistant. Charge Tally tworzy wpisy ładowania na podstawie istniejących czujników energii lub mocy. Każdy wpis możesz przypisać do pojazdu, kierowcy lub innej wybranej nazwy.

- Korzystaj ze stałej ceny, czujnika ceny lub różnych cen w zależności od pory dnia.
- Wykrywaj ładowanie automatycznie albo samodzielnie rozpoczynaj i kończ wpisy.
- Sprawdzaj energię i koszty dla każdej tożsamości za dzisiaj, bieżący miesiąc i rok.
- Dodawaj wcześniejsze ładowania i poprawiaj ich szczegóły.
- Przeglądaj dane i zarządzaj nimi za pomocą karty na pulpicie.

> Miejsce na zrzut ekranu: karta pulpitu ze stanem ładowania, wyborem tożsamości i statystykami.

## Zanim zaczniesz

Potrzebujesz Home Assistant i co najmniej jednego czujnika mierzącego obwód ładowania. Charge Tally zapisuje ładowania; nie włącza ani nie wyłącza ładowarki.

Wymaga **Home Assistant 2025.3.4 lub nowszej wersji**. Przetestowano z wersjami 2025.3.4, 2025.12.4, 2026.3.4 i 2026.9.1.

| Dostępne czujniki | Wybór podczas konfiguracji |
| --- | --- |
| Narastający odczyt energii w Wh, kWh lub MWh | **Tylko energia** |
| Moc w W lub kW | **Tylko moc** — Home Assistant oblicza zużytą energię |
| Oba rodzaje | **Energia i moc** — energia służy do pomiaru zużycia, a moc do wykrywania ładowania |

Narastający odczyt energii to wskazanie licznika, które zwykle rośnie, a nie samo zużycie z ostatniej godziny. Automatyczne wykrywanie wymaga czujnika mocy.

## Instalacja przez HACS

1. Otwórz **HACS**, a następnie jego menu → **Niestandardowe repozytoria**.
2. Wpisz `https://github.com/enecess/ha-charge-tally` i wybierz **Integracja**.
3. Znajdź **Charge Tally** w HACS i pobierz integrację.
4. Uruchom ponownie Home Assistant.
5. Otwórz **Ustawienia → Urządzenia i usługi → Dodaj integrację** i wyszukaj **Charge Tally**.

Aby zainstalować ręcznie, skopiuj folder `custom_components/charge_tally` z repozytorium do folderu `custom_components` swojej instalacji Home Assistant, a następnie uruchom ją ponownie.

## Konfiguracja pierwszego punktu ładowania

1. **Wybierz walutę.** Obowiązuje ona we wszystkich punktach ładowania i nie można jej później zmienić dla tych samych zapisanych wpisów.
2. **Nazwij punkt ładowania**, wybierz rodzaj posiadanych czujników, a następnie wskaż te czujniki.
3. Jeśli masz czujnik mocy, zdecyduj, czy włączyć **automatyczne wykrywanie ładowania**. Ustaw progi mocy oraz czas, przez jaki muszą być spełnione, aby ładowanie się rozpoczęło lub zakończyło. Próg zakończenia musi być niższy od progu rozpoczęcia.
4. **Wybierz cenę energii** zgodnie z poniższą tabelą.
5. Wybierz potrzebne dzienne, miesięczne lub roczne liczniki energii i zakończ konfigurację.

Jeśli formularz punktu ładowania nie otworzy się automatycznie, otwórz **Charge Tally** w **Ustawienia → Urządzenia i usługi** i wybierz **Dodaj punkt ładowania**.

| Rodzaj ceny | Co podać |
| --- | --- |
| Cena stała | Cena za kWh |
| Cena dynamiczna | Czujnik ceny używający tej samej waluty co Charge Tally |
| Cena według pory dnia | Początek, koniec i cena każdego przedziału, obejmujących łącznie całą dobę |

Ceny według pory dnia powtarzają się codziennie. Przedział może przechodzić przez północ; koniec doby wpisz jako `24:00`. Obsługiwane są ceny zerowe i ujemne.

> Miejsce na zrzut ekranu: wybór czujników i konfiguracja cen energii.

Aby dodać kolejny punkt ładowania lub tożsamość, otwórz **Charge Tally** w **Ustawienia → Urządzenia i usługi**. Możesz tam również zmienić ustawienia istniejącego punktu. Przed zmianą pomiaru lub wykrywania zakończ jego bieżący wpis ładowania.

## Dodawanie karty do pulpitu

Edytuj pulpit, wybierz **Dodaj kartę** i wyszukaj **Charge Tally**. W edytorze karty wybierzesz wyświetlane punkty ładowania, tożsamości i informacje. Karta korzysta z języka i motywu Home Assistant.

Karta jest zwykle dostępna automatycznie. Jeśli jej brakuje, najpierw odśwież przeglądarkę. Jeśli samodzielnie zarządzasz zasobami pulpitu, dodaj `/charge_tally/charge-tally-card.js?v=0.1.2` jako **Moduł JavaScript** i ponownie odśwież stronę.

## Tożsamości i wpisy ładowania

Tożsamość może oznaczać samochód, członka rodziny lub cokolwiek innego, co chcesz śledzić osobno. Tożsamości są wspólne dla wszystkich punktów ładowania. Jeśli żadnej nie wybierzesz, dostępna jest **Unassigned**.

Wybierz tożsamość przed rozpoczęciem ładowania. Rozpoczęty wpis zachowuje tę tożsamość. Zmiana wyboru w trakcie ładowania przygotowuje **następny** wpis. Aby poprawić bieżący lub starszy wpis, użyj **Zmień tożsamość wpisu**.

Przy włączonym automatycznym wykrywaniu wpis rozpoczyna się i kończy po spełnieniu progów mocy i czasów oczekiwania. Krótkie przerwy mogą pozostać częścią tego samego wpisu. Bez wykrywania używaj przycisków **Rozpocznij wpis** i **Zakończ wpis** na karcie.

We własnych automatyzacjach możesz użyć encji **Tożsamość** punktu ładowania, aby wybrać, kto ładuje. Na przykład czytnik RFID lub przycisk może zmienić ten wybór. Lista akcji automatyzacji udostępnia też akcje Charge Tally do rozpoczynania i kończenia wpisów.

## Dodawanie i poprawianie wcześniejszych ładowań

1. Na karcie wybierz **Dodaj wpis historyczny** albo otwórz zakończony wpis i wybierz **Edytuj wpis**.
2. Wybierz punkt ładowania, tożsamość oraz czas rozpoczęcia i zakończenia.
3. Użyj dostępnej historii czujników lub samodzielnie wpisz całkowitą energię. Wybierz sposób obliczenia kosztu albo pozostaw go do uzupełnienia, jeśli jeszcze go nie znasz.
4. Wybierz **Podgląd zmian**, sprawdź wynik, a następnie wybierz **Zapisz podgląd**.

Dostępność historii zależy od danych zachowanych przez Home Assistant. Jeśli brakuje odczytów, możesz wpisać sumę z innego źródła, na przykład z historii ładowarki. Dwa wpisy tego samego punktu ładowania nie mogą nakładać się w czasie.

Użyj **Unieważnij wpis**, aby wykluczyć błędny wpis z podsumowań. Jego wcześniejsze szczegóły pozostaną dostępne do wglądu.

> Miejsce na zrzut ekranu: wcześniejszy wpis ładowania i podgląd zmian przed zapisaniem.

## Jak rozumieć podsumowania

- **Ładowanie przez północ:** zużycie jest dzielone między odpowiednie daty. Dotyczy to także zmiany miesiąca i roku. Jeśli odczyty licznika obejmują taki moment, podział jest szacowany na podstawie upływu czasu.
- **Ładowanie w toku:** wartości mogą się zmieniać wraz z kolejnymi odczytami lub po potwierdzeniu ostatecznego czasu zakończenia.
- **Koszt do uzupełnienia:** brakuje niektórych cen. Wyświetlana znana kwota to tylko część kosztu, a nie kwota końcowa.
- **Sumy liczników i wpisów mogą się różnić:** liczniki obejmują też energię zużytą poza wpisami ładowania, na przykład w trybie czuwania. Podsumowania tożsamości obejmują tylko przypisane do niej wpisy. Poprawienie wpisu aktualizuje statystyki wpisów, a nie historię licznika.

## Częste pytania

**Dlaczego nie ma wpisu ładowania?** Sprawdź, czy wybrane czujniki są dostępne. Przy automatycznym wykrywaniu sprawdź, czy jest ono włączone i czy moc pozostaje powyżej progu rozpoczęcia wystarczająco długo. W przeciwnym razie rozpocznij wpis ręcznie.

**Dlaczego koszt wymaga uzupełnienia?** Sprawdź czujnik ceny i jego walutę albo otwórz wpis i podaj znany koszt całkowity. Brakujące dane nie są traktowane jako koszt zerowy.

**Dlaczego Home Assistant prosi o naprawę punktu ładowania?** Jeden z liczników energii utworzonych dla tego punktu mógł zostać usunięty lub zmieniony. Otwórz powiadomienie o naprawie i postępuj zgodnie z instrukcjami.

**Jak bezpiecznie zaktualizować integrację?** Utwórz kopię zapasową Home Assistant, zaktualizuj Charge Tally przez HACS i uruchom ponownie Home Assistant. Usunięcie integracji nie kasuje zapisanych wpisów ładowania.

Potrzebujesz pomocy? [Zgłoś problem](https://github.com/enecess/ha-charge-tally/issues), podając wersje Home Assistant i Charge Tally oraz opis problemu.

[Licencja MIT](LICENSE)
