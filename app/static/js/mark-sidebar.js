document.addEventListener("DOMContentLoaded", () => {
    const body = document.body;
    const sidebar = document.getElementById("markSidebar");
    const toggle = document.getElementById("markSidebarToggle");
    const overlay = document.getElementById("markSidebarOverlay");

    if (!sidebar || !toggle) {
        return;
    }

    const setOpen = (isOpen) => {
        body.classList.toggle("mark-sidebar-open", isOpen);
        toggle.setAttribute("aria-expanded", String(isOpen));
        toggle.setAttribute(
            "aria-label",
            isOpen ? "Close navigation" : "Open navigation"
        );

        if (overlay) {
            overlay.setAttribute("aria-hidden", String(!isOpen));
        }
    };

    toggle.addEventListener("click", () => {
        setOpen(!body.classList.contains("mark-sidebar-open"));
    });

    if (overlay) {
        overlay.addEventListener("click", () => setOpen(false));
    }

    sidebar.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => setOpen(false));
    });

    window.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setOpen(false);
        }
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 900) {
            setOpen(false);
        }
    });
});
