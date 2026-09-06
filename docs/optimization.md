# Постановка математичної задачі MILP-оптимізації BESS (SPEC §9)

**Модуль:** `ems.optimization.milp`  
**Розв'язувач:** PuLP + CBC (`PULP_CBC_CMD`)  
**Цільовий горизонт:** $T = 24 \dots 48$ кроків (за замовчуванням $T=24$ або $T=48$).  
**Крок дискретизації:** $\Delta t \in \{1.0, 0.25\}$ години (1 год за замовчуванням, 15 хв опційно).  

---

## 1. Індекси та множини

- Часові інтервали: $t \in \mathcal{T} = \{0, 1, 2, \dots, T-1\}$.

---

## 2. Вхідні параметри

### 2.1. Ринкові та системні ряди (на кожен інтервал $t \in \mathcal{T}$)
- $price\_buy[t]$ — тариф купівлі електроенергії з мережі (грн/кВт·год):  
  $$price\_buy[t] = \frac{Price_{DAM}[t] + Tariff_{trans} + Tariff_{dist} + Margin_{supp}}{1000}$$
- $price\_sell[t]$ — тариф продажу (експорту) електроенергії в мережу (грн/кВт·год):  
  $$price\_sell[t] = \frac{Price_{DAM}[t] \times k_{export}}{1000} \quad (\text{0, якщо експорт заборонено})$$
- $load[t]$ — електричне навантаження об'єкта / підприємства (кВт).
- $pv[t]$ — потужність генерації сонячної СЕС (кВт).

### 2.2. Параметри BESS (акумуляторної системи)
- $Capacity$ — номінальна ємність батареї (кВт·год, за замовчуванням 2000 кВт·год).
- $P_{ch\_max}, P_{dis\_max}$ — максимальна потужність заряду / розряду інвертора (кВт, за замовчуванням 500 кВт).
- $\eta_{ch}, \eta_{dis}$ — ККД заряду та розряду (за замовчуванням по 0.95, круговий ККД $\eta_{rt} \approx 90.25\%$).
- $soc_{min\_pct}, soc_{max\_pct}$ — допустимі межі заряду у % (10% та 90%).
  - $soc_{min} = Capacity \times \frac{soc_{min\_pct}}{100}$ (кВт·год).
  - $soc_{max} = Capacity \times \frac{soc_{max\_pct}}{100}$ (кВт·год).
- $soc_0$ — початковий запас енергії в батареї з поточної телеметрії (кВт·год).
- $soc_{end\_target}$ — цільовий мінімальний залишок енергії наприкінці горизонту (кВт·год, за замовчуванням $= soc_0$).
- $self\_discharge$ — втрати на саморозряд за інтервал $\Delta t$ (кВт·год):  
  $self\_discharge = Capacity \times \frac{k_{self}}{100} \times \frac{\Delta t}{24 \times 30}$ (мала величина $\approx 0$).
- $c_{deg}$ — питома вартість деградації акумулятора (грн/кВт·год перенесеної енергії):  
  $$c_{deg} = \frac{CAPEX}{2 \times CycleLife \times Capacity} \approx 1.25\text{ грн/кВт·год}$$

### 2.3. Параметри мережі та стратегії
- $peak\_limit\_kw$ — контрактний ліміт потужності імпорту з мережі (кВт).
- $c_{peak}$ — тариф за пікову потужність або штраф за перебір (грн/кВт).
- $soc_{reserve}$ — аварійний резерв ємності (кВт·год) для стратегії `BACKUP_RESERVE`:  
  $soc_{reserve} = Capacity \times \frac{reserve\_soc\_pct}{100}$.
- Ваги цільової функції:
  - $w_{arb} \ge 0$ — вага ринкового арбітражу.
  - $w_{peak} \ge 0$ — вага зрізання піків (peak-shaving).
  - $w_{reserve} \ge 0$ — вага підтримання аварійного резерву.
  - $w_{self} \ge 0$ — вага максимізації власного споживання СЕС.
- $export\_allowed \in \{True, False\}$ — чи дозволено експорт надлишків у мережу ОЕС.

---

## 3. Змінні оптимізації (Decision Variables)

Для кожного $t \in \mathcal{T}$:
1. $p_{ch}[t] \ge 0$ — потужність заряду батареї (кВт).
2. $p_{dis}[t] \ge 0$ — потужність розряду батареї (кВт).
3. $z[t] \in \{0, 1\}$ — бінарна змінна блокування одночасного заряду та розряду ($z[t]=1$ заряд дозволено, $z[t]=0$ розряд дозволено).
4. $soc[t] \ge 0$ — енергія в батареї на кінець інтервалу $t$ (кВт·год).
5. $g_{imp}[t] \ge 0$ — імпорт енергії з мережі за крок $t$ (кВт·год).
6. $g_{exp}[t] \ge 0$ — експорт енергії в мережу за крок $t$ (кВт·год).
7. $slack_{reserve}[t] \ge 0$ — дефіцит заряду відносно аварійного резерву (кВт·год).

Глобальна змінна горизонту:
8. $peak \ge 0$ — максимальна пікова потужність імпорту з мережі на горизонті (кВт).

---

## 4. Цільова функція (Objective Function)

Мінімізувати сумарні витрати підприємства на електроенергію з урахуванням вартості деградації BESS та штрафів стратегій:

$$\begin{aligned}
\min \quad & \sum_{t=0}^{T-1} \Big[ price\_buy[t] \cdot g_{imp}[t] - price\_sell[t] \cdot g_{exp}[t] + c_{deg} \cdot \big(p_{ch}[t] + p_{dis}[t]\big) \cdot \Delta t \Big] \\
& + w_{peak} \cdot c_{peak} \cdot peak \\
& + w_{reserve} \cdot c_{reserve\_penalty} \cdot \sum_{t=0}^{T-1} slack_{reserve}[t]
\end{aligned}$$

*Примітка щодо розмірностей:*
- $price\_buy[t]$ [грн/кВт·год] $\times$ $g_{imp}[t]$ [кВт·год] = [грн].
- $price\_sell[t]$ [грн/кВт·год] $\times$ $g_{exp}[t]$ [кВт·год] = [грн].
- $c_{deg}$ [грн/кВт·год] $\times (p_{ch} + p_{dis}) \cdot \Delta t$ [кВт·год] = [грн].
- $c_{peak}$ [грн/кВт] $\times peak$ [кВт] = [грн].
- $c_{reserve\_penalty}$ [грн/кВт·год] $\times slack_{reserve}[t]$ [кВт·год] = [грн].

---

## 5. Обмеження (Constraints) — Відповідність SPEC §9.3 (1:1)

### 5.1. Динаміка заряду батареї (SPEC §9.3, рядок 350)
Для першого кроку $t=0$:
$$soc[0] = soc_0 + \eta_{ch} \cdot p_{ch}[0] \cdot \Delta t - \frac{p_{dis}[0] \cdot \Delta t}{\eta_{dis}} - self\_discharge$$

Для всіх наступних кроків $t \in \{1, \dots, T-1\}$:
$$soc[t] = soc[t-1] + \eta_{ch} \cdot p_{ch}[t] \cdot \Delta t - \frac{p_{dis}[t] \cdot \Delta t}{\eta_{dis}} - self\_discharge$$

### 5.2. Допустимі межі SoC (SPEC §9.3, рядок 351)
$$soc_{min} \le soc[t] \le soc_{max} \quad \forall t \in \mathcal{T}$$

### 5.3. Цільовий залишок енергії (SPEC §9.3, рядок 352)
$$soc[T-1] \ge soc_{end\_target}$$

### 5.4. Потужність інвертора та заборона одночасного заряду/розряду (SPEC §9.3, рядок 353)
$$p_{ch}[t] \le P_{ch\_max} \cdot z[t] \quad \forall t \in \mathcal{T}$$
$$p_{dis}[t] \le P_{dis\_max} \cdot (1 - z[t]) \quad \forall t \in \mathcal{T}$$
де $z[t] \in \{0, 1\}$.

### 5.5. Баланс енергії об'єкта (SPEC §9.3, рядок 354)
$$g_{imp}[t] - g_{exp}[t] = \Big( load[t] + p_{ch}[t] - p_{dis}[t] - pv[t] \Big) \cdot \Delta t \quad \forall t \in \mathcal{T}$$
з граничними умовами:
$$g_{imp}[t] \ge 0, \quad g_{exp}[t] \ge 0 \quad \forall t \in \mathcal{T}$$

### 5.6. Зрізання піків (Peak Shaving) (SPEC §9.3, рядок 355)
Потужність імпорту на кожному кроці не перевищує пікову змінну $peak$:
$$g_{imp}[t] \le peak \cdot \Delta t \quad \forall t \in \mathcal{T}$$

Якщо увімкнено жорсткий Peak Shaving:
$$peak \le peak\_limit\_kw$$

### 5.7. Обмеження експорту в мережу (SPEC §9.3, рядок 356)
Якщо експорт заборонений ($export\_allowed = False$):
$$g_{exp}[t] = 0 \quad \forall t \in \mathcal{T}$$

Якщо експорт дозволений:
$$g_{exp}[t] \le export\_limit\_kw \cdot \Delta t \quad \forall t \in \mathcal{T}$$

### 5.8. Лінеаризація штрафу за резерв (SPEC §9.2, рядок 344)
$$slack_{reserve}[t] \ge soc_{reserve} - soc[t] \quad \forall t \in \mathcal{T}$$
$$slack_{reserve}[t] \ge 0 \quad \forall t \in \mathcal{T}$$

---

## 6. Профілі стратегій (§6.7)

| Стратегія | $w_{arb}$ | $w_{peak}$ | $w_{reserve}$ | Додаткові обмеження |
|---|---|---|---|---|
| `ARBITRAGE` | 1.0 | 0.0 | 0.0 | Стандартні межі |
| `PEAK_SHAVING` | 0.2 | 1.0 | 0.0 | $peak \le peak\_limit\_kw$ |
| `SELF_CONSUMPTION`| 0.5 | 0.0 | 0.0 | $price\_sell \to 0$, мінімізація $g_{imp}$ |
| `BACKUP_RESERVE` | 0.5 | 0.0 | 1.0 | $soc_{reserve} = Capacity \times reserve\_soc$ |

Комбіновані стратегії формуються зваженою сумою відповідних коефіцієнтів.

---

## 7. Розрахунок метрик графіка (Вихід, SPEC §9.4)

1. **Очікуваний прибуток / економія:**
   $$ExpectedProfit = Cost_{baseline} - Cost_{actual}$$
   де:
   $$Cost_{baseline} = \sum_{t} \max(0, load[t] - pv[t]) \cdot \Delta t \cdot price\_buy[t]$$
   $$Cost_{actual} = \sum_{t} \big( g_{imp}[t] \cdot price\_buy[t] - g_{exp}[t] \cdot price\_sell[t] + c_{deg} \cdot (p_{ch}[t] + p_{dis}[t]) \cdot \Delta t \big)$$
2. **Еквівалентна кількість циклів:**
   $$Cycles = \frac{\sum_{t} (p_{ch}[t] + p_{dis}[t]) \cdot \Delta t}{2 \times Capacity}$$
3. **Час розв'язання (CBC):**
   Вимірюється у мілісекундах (`solve_time_ms`), вимога: $< 2000$ мс для $T=48$.
