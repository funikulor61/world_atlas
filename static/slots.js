// ============ «Набор букв» — слот-машина как в vvod.html ============
// Единственный способ заполнить поля логина и пароля: клик по барабану
// вписывает его символ в ВЫБРАННОЕ поле (список «Куда писать»).
// После каждого введённого символа барабаны автоматически прокручиваются
// заново — те же буквы второй раз не выпадут. Ручной ввод с клавиатуры,
// вставка и автозаполнение отключены: поля readonly, а этот скрипт
// дополнительно перехватывает события.
// Случайная перестановка барабанов — кнопкой «Крутить».

const LAYOUTS = {
    en: {
        letters: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'.split(''),
        symbols: ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+', '~', '?',
                  '1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
    }
};

// случайные count разных символов из массива
function pickRandom(items, count) {
    const shuffled = [...items].sort(() => 0.5 - Math.random());
    return shuffled.slice(0, count);
}

// один барабан крутится duration миллисекунд и останавливается на символе
function spinReel(reel, pool, finalChar, duration) {
    return new Promise(function (resolve) {
        reel.classList.add("spinning");
        const timer = setInterval(function () {
            reel.textContent = pool[Math.floor(Math.random() * pool.length)];
        }, 50);
        setTimeout(function () {
            clearInterval(timer);
            reel.textContent = finalChar;
            reel.classList.remove("spinning");
            resolve();
        }, duration);
    });
}

// подсветка подсказки, когда пользователь пытается ввести букву вручную
function hintBlocked(machine) {
    const hint = machine.querySelector(".slot-hint");
    if (!hint) return;
    hint.classList.remove("blocked");
    void hint.offsetWidth;               // перезапуск CSS-анимации
    hint.classList.add("blocked");
}

// настраиваем одну слот-машину (на странице их может быть несколько)
function setupSlotMachine(machine) {
    const targetSelect = machine.querySelector(".target-select");
    const layoutSelect = machine.querySelector(".layout-select");
    const reelsBox = machine.querySelector(".reels");
    const spinBtn = machine.querySelector(".spin-btn");
    const backBtn = machine.querySelector(".back-btn");
    const clearBtn = machine.querySelector(".clear-btn");
    const card = machine.closest(".card");
    const form = card ? card.querySelector("form") : null;
    const fields = Array.from(document.querySelectorAll("[data-slot-field]"));
    let isSpinning = false;

    // поле, в которое сейчас пишут барабаны
    function targetField() {
        return document.getElementById(targetSelect.value);
    }

    // подсвечиваем активное поле, чтобы было видно, куда попадут буквы
    function markTarget() {
        const active = targetField();
        fields.forEach(function (f) { f.classList.toggle("slot-target", f === active); });
    }

    // создаём барабан: кнопка с символом (буква или знак)
    function makeReel(isSymbol) {
        const reel = document.createElement("button");
        reel.type = "button";
        reel.className = "reel" + (isSymbol ? " symbol" : "");
        reel.textContent = "?";
        reel.addEventListener("click", function () {
            if (isSpinning || reel.textContent === "?") return;
            const field = targetField();
            if (!field) return;
            field.value += reel.textContent;   // символ — в выбранное поле
            field.focus();
            reel.style.background = "#5fbf74"; // зелёная вспышка выбора
            setTimeout(function () { reel.style.background = ""; }, 150);
            spinAll(true);   // барабан обновился — крутим заново и быстрее
        });
        return reel;
    }

    // все 8 барабанов крутятся и останавливаются по очереди;
    // fast=true — короткий автопрокрут после введённого символа
    async function spinAll(fast) {
        if (isSpinning) return;
        isSpinning = true;
        spinBtn.disabled = true;
        const layout = LAYOUTS[layoutSelect.value];
        const letters = pickRandom(layout.letters, 5);
        const symbols = pickRandom(layout.symbols, 3);
        const jobs = [];
        Array.from(reelsBox.children).forEach(function (reel, i) {
            const isSymbol = reel.classList.contains("symbol");
            const pool = isSymbol ? layout.symbols : layout.letters;
            const finals = isSymbol ? symbols : letters;
            const k = isSymbol ? i - 5 : i;       // у знаков своя нумерация
            const duration = (fast ? 180 : 400) + k * (fast ? 60 : 150);
            jobs.push(spinReel(reel, pool, finals[k], duration));
        });
        await Promise.all(jobs);
        isSpinning = false;
        spinBtn.disabled = false;
        // раскладку могли переключить прямо во время прокрута —
        // сразу перекручиваем барабаны с новой раскладкой
        if (layout !== LAYOUTS[layoutSelect.value]) spinAll();
    }

    // --- запрет ручного ввода: клавиатура, вставка, вырезание, перетаскивание ---
    fields.forEach(function (field) {
        ["keydown", "paste", "cut", "drop", "dragover"].forEach(function (evt) {
            field.addEventListener(evt, function (e) {
                e.preventDefault();
                hintBlocked(machine);
            });
        });
    });

    // --- проверка перед отправкой формы: барабаны должны быть использованы ---
    if (form) {
        form.addEventListener("submit", function (e) {
            const empty = fields.filter(function (f) { return !f.value; });
            if (empty.length) {
                e.preventDefault();
                const names = empty.map(function (f) {
                    const label = f.labels[0] ? f.labels[0].textContent : f.id;
                    return label.split("(")[0].trim();
                });
                alert("Пустые поля: " + names.join(", ") +
                      ". Наберите их барабанами слот-машины.");
            }
        });
    }

    for (let i = 0; i < 5; i++) reelsBox.appendChild(makeReel(false));
    for (let i = 0; i < 3; i++) reelsBox.appendChild(makeReel(true));

    // spinAll получает fast=true после каждого символа, поэтому слушатели
    // кнопки и раскладки передают вызов через обёртку, а не саму функцию
    spinBtn.addEventListener("click", function () { spinAll(); });
    // «⌫ Стереть» — возврат на один символ назад (как Backspace)
    if (backBtn) backBtn.addEventListener("click", function () {
        const field = targetField();
        if (field && field.value) {
            field.value = field.value.slice(0, -1);
            field.focus();
        }
    });
    clearBtn.addEventListener("click", function () {
        const field = targetField();
        if (field) { field.value = ""; field.focus(); }
    });
    targetSelect.addEventListener("change", markTarget);
    layoutSelect.addEventListener("change", function () { spinAll(); });

    markTarget();
    spinAll();   // первый автоматический прокрут при загрузке страницы
}

// запускаем все слот-машины на странице
document.querySelectorAll(".slot-machine").forEach(setupSlotMachine);
