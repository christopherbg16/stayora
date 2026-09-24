// Smooth scroll behavior
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        // Skip bare "#" links (dropdown/modal toggles, placeholders) - there's
        // nothing to scroll to and querySelector('#') throws a syntax error.
        if (!href || href === '#') {
            return;
        }
        const target = document.querySelector(href);
        if (!target) {
            return;
        }
        e.preventDefault();
        target.scrollIntoView({
            behavior: 'smooth'
        });
    });
});

// Add fade-in animation to cards
document.addEventListener('DOMContentLoaded', function() {
    const cards = document.querySelectorAll('.card');
    cards.forEach((card, index) => {
        card.style.opacity = '0';
        card.style.animation = `fadeInUp 0.5s ease forwards ${index * 0.1}s`;
    });
});

// Add hover effect to all buttons
document.querySelectorAll('.btn').forEach(btn => {
    btn.addEventListener('mouseenter', function() {
        this.style.transform = 'translateY(-2px)';
    });

    btn.addEventListener('mouseleave', function() {
        this.style.transform = 'translateY(0)';
    });
});

// Add parallax effect to background
window.addEventListener('scroll', function() {
    const scrolled = window.pageYOffset;
    const bg = document.querySelector('.auth-page');
    if (bg) {
        bg.style.backgroundPositionY = -(scrolled * 0.5) + 'px';
    }
});

// Theme toggle functionality
function toggleTheme() {
    const htmlElement = document.documentElement;
    const icon = document.getElementById('theme-toggle-icon');
    const isDark = htmlElement.getAttribute('data-theme') === 'dark';

    if (isDark) {
        htmlElement.removeAttribute('data-theme');
        if (icon) {
            icon.classList.remove('fa-sun');
            icon.classList.add('fa-moon');
        }
        localStorage.setItem('theme', 'light');
    } else {
        htmlElement.setAttribute('data-theme', 'dark');
        if (icon) {
            icon.classList.remove('fa-moon');
            icon.classList.add('fa-sun');
        }
        localStorage.setItem('theme', 'dark');
    }
}

// Initialize theme on page load
document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme');
    const htmlElement = document.documentElement;
    const icon = document.getElementById('theme-toggle-icon');
    const isDark = savedTheme === 'dark';

    if (isDark) {
        htmlElement.setAttribute('data-theme', 'dark');
    } else {
        // Default to light theme if no preference saved
        htmlElement.removeAttribute('data-theme');
    }

    if (icon) {
        icon.classList.toggle('fa-sun', isDark);
        icon.classList.toggle('fa-moon', !isDark);
    }
});