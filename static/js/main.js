// main.js — students will add JavaScript here as features are built

(function () {
    const FLASH_AUTO_DISMISS_MS = 10000;
    const FADE_MS = 300;

    function dismiss(flash) {
        if (!flash || flash.dataset.dismissed === "1") return;
        flash.dataset.dismissed = "1";
        flash.classList.add("flash--dismissing");
        setTimeout(() => flash.remove(), FADE_MS);
    }

    document.querySelectorAll(".flash").forEach((flash) => {
        const closeBtn = flash.querySelector(".flash-close");
        if (closeBtn) {
            closeBtn.addEventListener("click", () => dismiss(flash));
        }
        setTimeout(() => dismiss(flash), FLASH_AUTO_DISMISS_MS);
    });
})();
