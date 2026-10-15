# RESEARCH SKELETON – StayOra (дипломен проект)

## 1. Контекст и обект на изследване

- **Проект/система:** StayOra – уеб платформа за търсене и резервация на настанявания (хотели, апартаменти, вили, курорти) с чатбот (Gemini 2.5 Flash) и интегрирано плащане (Stripe). Стек: Flask, Supabase (PostgreSQL), scikit-learn и др.
- **Обект:** Прогнозиране на цената за нощувка (EUR) на обект за настаняване в платформата StayOra.
- **Предмет:** Влияние на инженеринг признак (взаимодействие „звезди × log(брой ревюта)“) върху MAE на Random Forest регресор спрямо базови модели.
- **Авторски (подобрен) модел:** Random Forest Regressor с 3 признака: `stars`, `review_count`, `engineered_stars_reviews = stars × log1p(review_count)`.
- **Базов (класически) модел:** Random Forest Regressor с 2 признака `stars`, `review_count`.
- **Тривиален модел:** DummyRegressor(strategy="mean").

## 2. Научен проблем

Съществуващите решения за прогнозиране на цена на настаняване в платформите за краткосрочен наем (Airbnb/Booking) са ориентирани към глобални данни и не отчитат смесен портфейл от имоти (хотел/апартамент/вила/курорт) и слаба локална метаданна (звезди, брой ревюта). Липсва адаптиран и валидиран модел, който с минимални, налични в StayOra признаци надминава тривиалното прогнозиране (средна цена) и линейния baseline с измерима разлика (MAE, RMSE).

## 3. Изследователски въпрос (RQ)

**Финален RQ (v4):** Намалява ли средната абсолютна грешка (MAE, EUR) на авторския Random Forest регресор с инженеринг признак `stars × log1p(review_count)` спрямо тривиалния DummyRegressor (средна цена) и класическия Random Forest с 2 признака, при оценка върху изолиран тестов набор (80/20, фиксиран seed) и 5-кратна кръстосана проверка върху набора от 1 200 записи за настанявания в StayOra, при ниво на значимост α = 0.05?

### 4 последователни версии на RQ

| Версия | Формулировка | Какво липсваше |
|---|---|---|
| v1 | „Може ли машинно обучение да предсказва цената на нощувка?“ | Няма метод, данни, сравнение, метрика |
| v2 | „Предсказва ли Random Forest цената по-добре от средната цена?“ | Няма явна метрика и данни |
| v3 | „Сравнява ли се Random Forest с engineered признак по MAE срещу DummyRegressor?“ | Няма праг на значимост и ясен protocol |
| v4 (финал) | (виж по-горе) | Метод, данни, сравнение, метрика, стат. тест |

### FINER критерии (таблица)

| Критерий | Въпрос | Оценка (1–5) | Вашата оценка |
|---|---|---|---|
| **F**easible | Има ли данни, компютърни ресурси, умения и време? | 5 | Да – 1 200 записа, scikit-learn, локално изчисление |
| **I**nteresting | Вълнува ли темата общността/бизнеса? | 4 | Да – ценообразуването в туризма |
| **N**ovel | Добавя ли нещо ново спрямо съществуващото? | 3 | Частично – engineered признак за локален смесен пазар |
| **E**thical | Има ли етични проблеми (поверителност, bias)? | 5 | Не – анонимизирани агрегирани данни, без лични данни |
| **R**elevant | Важна ли е за науката/практика? | 4 | Да – приложимо в revenue management |

**LINER score (F+I+N+E+R): 21/25.**

## 4. Хипотеза

- **H₀ (нулевата):** Авторският Random Forest модел **не** постига статистически значимо по-ниска MAE от тривиалния DummyRegressor (средна цена) – т.е. MAE_author ≥ MAE_dummy − δ при α = 0.05.
- **H₁ (алтернативната):** Авторският Random Forest модел постига статистически значимо по-ниска MAE от DummyRegressor с абсолютна разлика ≥ 0.5 EUR и мащабно подобрение спрямо линейния базов модел с ≥ 10% намаление на MAE.

**„Хипотезата ще е опровергана, ако MAE на авторския модел не е по-ниска от MAE на DummyRegressor с поне 5% относително подобрение или ако двустранният t-тест върху 5 кръстосани грешки даде p ≥ 0.05.“**

**Обосноваване (защото…)**: …защото проучванията върху ценообразуването в платформите за краткосрочен наем показват, че ансамбловите дървовидни модели (Random Forest, XGBoost) надминават линейните и средни базови модели при наличието на нелинейни взаимодействия между рейтинг (звезди) и популярност (брой ревюта) (Kalehbasti, Nikolenko & Rezaei, 2021; Tang, Cheng & Zhang, 2024); защото взаимодействието „звезди × log(ревюта)“ моделира ефекта на popular/high-quality комбинация, който линейната регресия не може да улови (Chapman, Mohammad & Villegas, 2023); и защото metrics-базираният protocol в Data in Brief (Antonio, de Almeida & Nunes, 2019) подкрепя използването на MAE/RMSE като основни метрики при ценови прогнози.

## 5. Базови модели (Baseline) и експеримент (notebook)

- Папка: `notebooks/`
- Файл: `notebooks/baseline_vs_authored.ipynb` (съвместим с Google Colab).
- Съдържание:
  1. Тривиален модел: `DummyRegressor(strategy="mean")`.
  2. Класически модел: `LinearRegression` / `RandomForestRegressor` с 2 признака `stars`, `review_count`.
  3. Авторски модел: `RandomForestRegressor` с 3 признака (+ `engineered_stars_reviews`).
- Изчислявани метрики: **MAE**, **RMSE** (и R² за справка).
- Протокол: 80/20 train/test split (random_state=42), 5-кратна CV, paired t-тест върху грешките.

## 6. Сравнителна таблица и ниша (Research Gap)

### Сравнителна таблица

| Източник | Задача | Данни | Метод | Резултат | Ограничение |
|---|---|---|---|---|---|
| Kalehbasti, Nikolenko & Rezaei (2021), arXiv CD-MAKE | Прогнозиране на Airbnb цена | Airbnb (NY/SF) | LR, RF, SVM, NN + sentiment | RF dobrе; sentiment помага | Ориентиран към един град; не обхваща смесени типове имоти |
| Tang, Cheng & Zhang (2024), MDE | Прогнозиране Airbnb цена | Въздушни обяви | 10 ML алгоритми | RF/GBDT най-добри по RMSE | Фокус Airbnb; без български/локален пазар |
| Chapman, Mohammad & Villegas (2023), arXiv | Динамика на цените Airbnb | Austin, TX | RF + feature engineering | Висока точност MAE/RMSE | Локален dataset; липса на cross-market валидация |
| Zhu et al. (2022), arXiv | Elasticity за occupancy prediction | Hotel booking platform | Custom neural elasticity | Подобрява occupancy/RMSE | Сложен; нужни голям обем occupancy данни |
| Antonio, de Almeida & Nunes (2019), Data in Brief | Набор данни booking demand | Hotels (Booking) | Описателна база | Стандартен dataset за ML | Не съдържа ценови таргет за регресия по имот |
| Tan, Su et al. (2024), Sustainability | Устойчиво прогнозиране цена | Airbnb | Deep learning multimodal | По-добро от ML baseline | Изисква image/text; скъпо |
| Wang & 2023 ACM | Airbnb HK цени | Airbnb Hong Kong | ML регресия | XGBoost най-добър | Регионален; без базови линейни сравнения |
| Altexsoft (blog) | Обзор pricing | — | Различни | — | Неакадемичен; липсва репродуцируемост |

**Нишата е:** липса на адаптиран за смесен портфейл от имоти (хотел/апартамент/вила/курорт) и локални метаданни (звезди, брой ревюта) в платформи като StayOra модел, който надминава тривиалното и линейното прогнозиране с минимум engineered признак.

## 7. Научна литература (Zotero експорт & CRAAP)

Списък от 10 източника (≥ 5 научни от arXiv / Semantic Scholar / Google Scholar). Всеки с 2 изречения и CRAAP оценка (5–25).

### Списък (IEEE/APA стил)

1. P. R. Kalehbasti, L. Nikolenko, H. Rezaei, "Airbnb Price Prediction Using Machine Learning and Sentiment Analysis," in *CD-MAKE 2021*, Springer, pp. 173–184, 2021. arXiv:1907.12665.
2. J. Tang, J. Cheng, M. Zhang, "Forecasting Airbnb prices through machine learning," *Managerial and Decision Economics*, vol. 45, no. 1, pp. 148–160, 2024. DOI: 10.1002/mde.3985.
3. S. Chapman, S. Mohammad, K. Villegas, "Predicting Listing Prices In Dynamic Short Term Rental Markets Using Machine Learning Models," arXiv:2308.06929, 2023.
4. F. Zhu, W. Xiao, Y. Yu, Z. Wang, Z. Chen, Q. Lu, Z. Liu, M. Wu, S. Ni, "Modeling Price Elasticity for Occupancy Prediction in Hotel Dynamic Pricing," arXiv:2208.03135, 2022.
5. N. Antonio, A. de Almeida, L. Nunes, "Hotel booking demand datasets," *Data in Brief*, vol. 22, pp. 41–49, 2019. DOI: 10.1016/j.dib.2018.11.126.
6. Q. Wang et al., "Machine Learning-Based Study on Airbnb Housing Price Prediction," *Proc. ACM*, 2023.
7. H. T. Tan, T. Su, X. Wu, P. Cheng, T. Zheng, "A Sustainable Rental Price Prediction Model Based on Multimodal Input and Deep Learning," *Sustainability*, vol. 16, no. 15, art. 6384, 2024. DOI: 10.3390/su16156384.
8. Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system. *KDD '16*, pp. 785–794. DOI: 10.1145/2939672.2939785.
9. Pedregosa, F., et al. (2011). Scikit-learn: Machine Learning in Python. *JMLR*, 12, pp. 2825–2830.
10. Breiman, L. (2001). Random forests. *Machine Learning*, 45(1), pp. 5–32. DOI: 10.1023/A:1010933404324.

### CRAAP бележки и оценки

| # | Име на източника (академичен) | 2 изречения | CRAAP (5–25) |
|---|---|---|---|
| 1 | Kalehbasti et al. (2021) | Статията изследва прогнозиране на цена в Airbnb с машинно обучение и sentiment анализ. Подходяща като теоретична основа за RF baseline. | 22/25 |
| 2 | Tang et al. (2024) | Сравнява 10 ML алгоритма за цена в Airbnb. Дава доказателство, че ensemble-модели надминават линейни. | 23/25 |
| 3 | Chapman et al. (2023) | Проект за динамика на цените в Austin с RF и feature engineering. Полезна за аргумент за engineered признак. | 18/25 |
| 4 | Zhu et al. (2022) | Моделира price elasticity за occupancy prediction. Показва сложността на динамичното ценообразуване. | 20/25 |
| 5 | Antonio et al. (2019) | Представя dataset booking demand. Полезна за методология и метрики MAE/RMSE. | 24/25 |
| 6 | Wang (2023 ACM) | ML-базирано изследване на Airbnb Хонконг. Потвърждава RF/XGBoost. | 17/25 |
| 7 | Tan et al. (2024) | Deep learning + multimodal за цена. Висока точност, но изисква допълнителни данни. | 19/25 |
| 8 | Chen & Guestrin (2016) | XGBoost – основополагаща статия за дървовидни ensemble. Методологична референция. | 25/25 |
| 9 | Pedregosa et al. (2011) | Описание на scikit-learn. Необходима за reproductibility. | 25/25 |
| 10 | Breiman (2001) | Оригинална Random Forest статия. Теоретична основа за авторския модел. | 25/25 |

### Zotero експорт (инструкция)

- Създайте колекция `StayOra-Lit` в Zotero.
- Импортирайте BibTeX (виж `docs/references.bib`) .
- Експортирайте в CSL JSON: `File → Export Library → CSL JSON` → `docs/zotero_export.json`.
- Версията на износа се пази в repo.

## 8. Декларация за използване на ИИ

### Декларация за използване на изкуствен интелект

В рамките на дипломния проект е използван AI-инструмент (Google Gemini 2.5 Flash като част от продуктовата функционалност на StayOra и AI-асистенти при разработка). AI е използван за: генериране на шаблони на код, преводи, документация и предognitive анализ, но всички научни твърдения, алгоритмични решения и финалният код са проверени и отговорност носят авторът. Използваните източници са реални и проверени.

### Авторски принос

Авторският метод се различава от базовия модел само по едно нещо: добавянето на един engineered признак `engineered_stars_reviews = stars × log1p(review_count)` към същия Random Forest регресор (basic hyperparameters). Всеки друг компонент (algorithm, train/test split, seed, metrics) е идентичен, за да бъде експериментът валиден (ceteris paribus). Останалата част (Flask app, база, UI, чатбот) е инженерен принос на автора.

---

*Подготовено за проверка по изискванията на дипломен проект (Spring 2026).*
