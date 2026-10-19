# RESEARCH SKELETON – StayOra (дипломен проект)

> **Статус:** изследователски протокол. В хранилището няма проверен емпиричен CSV и не са изпълнявани модели; не представяйте синтетичните демонстрационни резултати като резултати от StayOra.

## 1. Контекст и обект на изследване

- **Проект/система:** StayOra – уеб платформа за търсене и резервация на настанявания (хотели, апартаменти, вили, курорти) с чатбот (Gemini 2.5 Flash) и интегрирано плащане (Stripe). Стек: Flask, Supabase (PostgreSQL), scikit-learn и др.
- **Обект:** Прогнозиране на цената за нощувка (EUR) на обект за настаняване в платформата StayOra.
- **Предмет:** Влияние на инженеринг признак (взаимодействие „звезди × log(брой ревюта)“) върху MAE на Random Forest регресор спрямо базови модели.
- **Авторски (подобрен) модел:** Random Forest Regressor с 3 признака: `stars`, `review_count`, `engineered_stars_reviews = stars × log1p(review_count)`.
- **Базови модели:** DummyRegressor(strategy="mean"), LinearRegression и Random Forest Regressor с 2 признака `stars`, `review_count`.
- **Данни:** предстои да се експортират от `hotels`; действителният брой редове, валутата, датата на извличане и правилата за почистване се записват след проверка. Стойността N=1 200 в notebook-а е само размер на синтетична демонстрация.
- **Тривиален модел:** DummyRegressor(strategy="mean").

## 2. Научен проблем

Съществуващите решения за прогнозиране на цена на настаняване в платформите за краткосрочен наем (Airbnb/Booking) са ориентирани към глобални данни и не отчитат смесен портфейл от имоти (хотел/апартамент/вила/курорт) и слаба локална метаданна (звезди, брой ревюта). Липсва адаптиран и валидиран модел, който с минимални, налични в StayOra признаци надминава тривиалното прогнозиране (средна цена) и линейния baseline с измерима разлика (MAE, RMSE).

## 3. Изследователски въпрос (RQ)

**Финален RQ (v4):** Намалява ли Random Forest с инженеринг признака `stars × log1p(review_count)` MAE спрямо DummyRegressor, линейна регресия и Random Forest с двата първоначални признака, когато моделите се оценяват върху един и същ изолиран тестов набор от проверени StayOra имоти? MAE се отчита в потвърдената валута на данните; размерът на набора се установява при експорта, а не се приема предварително.

Протокол: фиксиран 80/20 hold-out с seed 42; 5-fold CV се докладва описателно. Основната статистическа проверка е едностранен paired permutation test върху абсолютните грешки на hold-out редовете, с 95% bootstrap интервал на средната разлика и α = 0.05. Трябва предварително да се установи дали редовете са независими имоти; при повторни наблюдения split-ът трябва да е групиран по имот.

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
| **F**easible | Има ли данни, компютърни ресурси, умения и време? | 3 | Изисква се експорт и проверка на броя/пълнотата на редовете; scikit-learn работи локално |
| **I**nteresting | Вълнува ли темата общността/бизнеса? | 4 | Да – ценообразуването в туризма |
| **N**ovel | Добавя ли нещо ново спрямо съществуващото? | 3 | Частично – engineered признак за локален смесен пазар |
| **E**thical | Има ли етични проблеми (поверителност, bias)? | 5 | Не – анонимизирани агрегирани данни, без лични данни |
| **R**elevant | Важна ли е за науката/практика? | 4 | Да – приложимо в revenue management |

**LINER score:** преоценете след реалния експорт; предишният сбор 21/25 приемаше непотвърдени 1 200 записа.

## 4. Хипотеза

- **H₀ (нулева):** средната попарна разлика `MAE_authored − MAE_dummy` върху hold-out набора е не по-малка от нула.
- **H₁ (алтернативна):** средната попарна разлика `MAE_authored − MAE_dummy` е по-малка от нула при едностранно α = 0.05.

Практически значимото подобрение се задава предварително като най-малко 5% MAE намаление спрямо Dummy. Критерият е изпълнен само ако едностранният paired permutation test има p < 0.05, горната граница на 95% bootstrap интервала за разликата е под 0 и относителното намаление е поне 5%. Петте CV fold-а не се третират като независими наблюдения за t-тест.

**Обосноваване:** публикациите за прогнозиране на Airbnb цени (Kalehbasti et al., 2021; Chapman et al., 2023) мотивират сравнението с нелинейни модели, но не валидират автоматично този признак или резултати за StayOra. Взаимодействието е изследователска хипотеза, която трябва да бъде оценена върху реални данни; източникът за hotel booking demand описва друг тип задача и не се използва като доказателство за ценова точност.

## 5. Базови модели (Baseline) и експеримент (notebook)

- Папка: `notebooks/`
- Файл: `notebooks/baseline_vs_authored.ipynb` (съвместим с Google Colab).
- Съдържание:
  1. Тривиален модел: `DummyRegressor(strategy="mean")`.
  2. Базови модели: `LinearRegression` и `RandomForestRegressor` с 2 признака `stars`, `review_count`.
  3. Авторски модел: `RandomForestRegressor` с 3 признака (+ `engineered_stars_reviews`).
- Изчислявани метрики: **MAE**, **RMSE** (и R² за справка).
- Протокол: 80/20 train/test split (random_state=42), 5-кратна CV за описателно сравнение, paired permutation test върху hold-out грешките и bootstrap 95% интервал.

## 6. Сравнителна таблица и ниша (Research Gap)

### Сравнителна таблица

| Източник | Задача | Данни | Метод | Резултат | Ограничение |
|---|---|---|---|---|---|
| Kalehbasti, Nikolenko & Rezaei (2021), arXiv/CD-MAKE | Прогнозиране на Airbnb цена | Airbnb listings and reviews | ML, deep learning, NLP | Източникът разглежда price prediction и review-derived predictors; резултатите трябва да се извлекат от пълния текст преди количествено сравнение | Airbnb контекстът не доказва преносимост към StayOra |
| Tang, Cheng & Zhang (2024), MDE | Прогнозиране на Airbnb цена | Airbnb listings | ML сравнение | Да се попълни след проверка на пълния текст и метаданните | DOI е посочен, но проверката през издателя не беше достъпна |
| Chapman, Mohammad & Villegas (2023), arXiv | Прогнозиране на listing prices | Austin short-term rentals | ML и feature engineering | Проектът изследва цени и локални фактори; не се приема като доказателство за избрания StayOra признак | Локален проект, без директна cross-market валидация |
| Zhu et al. (2022), arXiv | Occupancy prediction и price elasticity | Онлайн хотелска платформа | Модел на търсене/еластичност | Различна целева променлива от цена на нощувка | Не е пряк baseline за тази регресионна задача |
| Antonio, de Almeida & Nunes (2019), Data in Brief | Hotel booking demand dataset | Хотелски резервации | Dataset article | Полезен за контекст на booking данни, не като price-per-property dataset | Не доказва точност на ценова регресия |
| Tan et al. (2024), Sustainability | Прогнозиране на rental price | Според посочения запис: multimodal inputs | Deep learning | Резултатът не е включен до проверка на пълния текст | Проверете авторите, входните данни и DOI метаданните |
| Breiman (2001), Machine Learning | Random Forest метод | Теоретична работа | Random Forest | Основополагащ методологичен източник | Не е специфичен за туризъм или StayOra |
| Pedregosa et al. (2011), JMLR | Scikit-learn | Софтуерна библиотека | ML implementation | Цитира библиотеката, използвана в експеримента | Софтуерна статия, не доказателство за бизнес хипотезата |
| Chen & Guestrin (2016), KDD | Gradient boosting | XGBoost | Система за boosting | Контекст за алтернативни дървовидни ансамбли | XGBoost не е модел в текущия експеримент |
| Nadeau & Bengio (2003), Machine Learning | Извод за generalization error | Методологична работа | Статистическа оценка | Подкрепя внимателното третиране на зависимостта при повторни train/test оценки | Не е ценова прогноза; използва се за методология |

**Работна ниша:** да се провери дали един предварително дефиниран interaction feature добавя стойност към ценова прогноза за смесен портфейл StayOra. Не твърдете, че в литературата липсва такъв модел, преди да извършите систематично търсене и да документирате стратегията за търсене.

## 7. Научна литература (Zotero експорт & CRAAP)

Работен списък от 10 източника. Библиографските записи се сверяват с издател/DOI/arXiv преди предаване; произволни общи CRAAP числа не се приписват без приложена рубрика.

### Списък (IEEE/APA стил)

1. P. R. Kalehbasti, L. Nikolenko, H. Rezaei, "Airbnb Price Prediction Using Machine Learning and Sentiment Analysis," in *CD-MAKE 2021*, Springer, pp. 173–184, 2021. arXiv:1907.12665.
2. J. Tang, J. Cheng, M. Zhang, "Forecasting Airbnb prices through machine learning," *Managerial and Decision Economics*, vol. 45, no. 1, pp. 148–160, 2024. DOI: 10.1002/mde.3985.
3. S. Chapman, S. Mohammad, K. Villegas, "Predicting Listing Prices In Dynamic Short Term Rental Markets Using Machine Learning Models," arXiv:2308.06929, 2023.
4. F. Zhu, W. Xiao, Y. Yu, Z. Wang, Z. Chen, Q. Lu, Z. Liu, M. Wu, S. Ni, "Modeling Price Elasticity for Occupancy Prediction in Hotel Dynamic Pricing," arXiv:2208.03135, 2022.
5. N. Antonio, A. de Almeida, L. Nunes, "Hotel booking demand datasets," *Data in Brief*, vol. 22, pp. 41–49, 2019. DOI: 10.1016/j.dib.2018.11.126.
6. C. Nadeau and Y. Bengio, "Inference for the Generalization Error," *Machine Learning*, vol. 52, no. 3, pp. 239–281, 2003. DOI: 10.1023/A:1024068626366.
7. H. T. Tan, T. Su, X. Wu, P. Cheng, T. Zheng, "A Sustainable Rental Price Prediction Model Based on Multimodal Input and Deep Learning," *Sustainability*, vol. 16, no. 15, art. 6384, 2024. DOI: 10.3390/su16156384.
8. Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system. *KDD '16*, pp. 785–794. DOI: 10.1145/2939672.2939785.
9. Pedregosa, F., et al. (2011). Scikit-learn: Machine Learning in Python. *JMLR*, 12, pp. 2825–2830.
10. Breiman, L. (2001). Random forests. *Machine Learning*, 45(1), pp. 5–32. DOI: 10.1023/A:1010933404324.

### Бележки за достоверност и релевантност

| # | Източник | Бележка | Статус |
|---|---|---|---|
| 1 | Kalehbasti et al. (2021) | ArXiv record confirms title, authors and journal reference; read full paper before summarizing comparative results. | Метаданни сверени с arXiv |
| 2 | Tang et al. (2024) | DOI supplied in the working citation; publisher metadata/results still require manual verification. | Непотвърден пълен текст |
| 3 | Chapman et al. (2023) | ArXiv confirms title, authors and Austin short-term rental focus. | Метаданни сверени с arXiv |
| 4 | Zhu et al. (2022) | ArXiv confirms title and authors; the task is occupancy/elasticity, not direct nightly-price regression. | Метаданни сверени с arXiv |
| 5 | Antonio et al. (2019) | Crossref confirms title, journal, volume, pages and DOI; the work describes booking-demand data. | Метаданни сверени с Crossref |
| 6 | Nadeau & Bengio (2003) | Crossref confirms title, authors, journal, pages and DOI; relevant to inference from model evaluation. | Метаданни сверени с Crossref |
| 7 | Tan et al. (2024) | Verify author list and reported methods/results against the publisher page; automated retrieval was blocked. | Нужна ръчна проверка |
| 8 | Chen & Guestrin (2016) | Method citation; verify formatting against ACM record before final submission. | Библиографска проверка |
| 9 | Pedregosa et al. (2011) | Standard scikit-learn citation; use it to document the software, not as evidence for the hypothesis. | Библиографска проверка |
| 10 | Breiman (2001) | Standard Random Forest citation; use it for the algorithm background. | Библиографска проверка |

За CRAAP оценка приложете една и съща 1–5 рубрика за Currency, Relevance, Authority, Accuracy и Purpose към всяка публикация и обосновете всяка стойност. Оценките остават непопълнени, докато тази проверка не бъде извършена.

### Zotero експорт (инструкция)

- Създайте колекция `StayOra-Lit` в Zotero.
- Импортирайте BibTeX (виж `docs/references.bib`) .
- Експортирайте в CSL JSON: `File → Export Library → CSL JSON` → `docs/zotero_export.json`.
- Експортът не е наличен в repo към момента; добавете го след Zotero проверката, не го описвайте като вече съхранен.

## 8. Декларация за използване на ИИ

### Декларация за използване на изкуствен интелект

Попълнете тази декларация според реално използваните инструменти, версии, дати и конкретни дейности. Авторът трябва самостоятелно да провери източниците, кода и научните твърдения и носи отговорност за финалния текст; настоящият шаблон не удостоверява, че всички източници вече са проверени.

### Авторски принос

Авторският метод се различава от базовия модел само по едно нещо: добавянето на един engineered признак `engineered_stars_reviews = stars × log1p(review_count)` към същия Random Forest регресор (basic hyperparameters). Всеки друг компонент (algorithm, train/test split, seed, metrics) е идентичен, за да бъде експериментът валиден (ceteris paribus). Останалата част (Flask app, база, UI, чатбот) е инженерен принос на автора.

---

*Подготовено за проверка по изискванията на дипломен проект (Spring 2026).*
