// Smooth scroll behavior
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        document.querySelector(this.getAttribute('href')).scrollIntoView({
            behavior: 'smooth'
        });
    });
});

// Add fade-in animation to cards
document.addEventListener('DOMContentLoaded', function() {
    const cards = document.querySelectorAll('.card');
    cards.forEach((card, index) => {
        card.style.animation = `fadeInUp 0.5s ease forwards ${index * 0.1}s`;
        card.style.opacity = '0';
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
    const isDark = htmlElement.getAttribute('data-theme') === 'dark';
    
    if (isDark) {
        htmlElement.removeAttribute('data-theme');
        document.getElementById('theme-toggle-icon').classList.remove('fa-sun');
        document.getElementById('theme-toggle-icon').classList.add('fa-moon');
        localStorage.setItem('theme', 'light');
    } else {
        htmlElement.setAttribute('data-theme', 'dark');
        document.getElementById('theme-toggle-icon').classList.remove('fa-moon');
        document.getElementById('theme-toggle-icon').classList.add('fa-sun');
        localStorage.setItem('theme', 'dark');
    }
}

// Initialize theme on page load
document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme');
    const htmlElement = document.documentElement;
    
    if (savedTheme === 'dark') {
        htmlElement.setAttribute('data-theme', 'dark');
        document.getElementById('theme-toggle-icon').classList.remove('fa-moon');
        document.getElementById('theme-toggle-icon').classList.add('fa-sun');
    } else if (savedTheme === 'light') {
        htmlElement.removeAttribute('data-theme');
        document.getElementById('theme-toggle-icon').classList.remove('fa-sun');
        document.getElementById('theme-toggle-icon').classList.add('fa-moon');
    } else {
        // Default to light theme if no preference saved
        htmlElement.removeAttribute('data-theme');
        document.getElementById('theme-toggle-icon').classList.remove('fa-sun');
        document.getElementById('theme-toggle-icon').classList.add('fa-moon');
    }
});