from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import json


class Profile(models.Model):
    """User's RPG character profile with stats and progression"""
    
    AVATAR_CHOICES = [
        ('scholar', 'Scholar'),
        ('warrior', 'Warrior'),
        ('mage', 'Mage'),
        ('rogue', 'Rogue'),
        ('artist', 'Artist'),
        ('explorer', 'Explorer'),
    ]
    
    PERSONALITY_CHOICES = [
        ('sensei', 'Strict Sensei'),
        ('buddy', 'Friendly Buddy'),
        ('rogue', 'Sarcastic Rogue'),
        ('mentor', 'Wise Mentor'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    avatar = models.CharField(max_length=20, choices=AVATAR_CHOICES, default='scholar')
    character_class = models.CharField(max_length=100, default='Novice Adventurer')
    level = models.IntegerField(default=1)
    
    # RPG Stats
    strength = models.IntegerField(default=10)
    intelligence = models.IntegerField(default=10)
    charisma = models.IntegerField(default=10)
    endurance = models.IntegerField(default=10)
    luck = models.IntegerField(default=10)
    
    # Experience and Progress
    total_xp = models.IntegerField(default=0)
    xp_to_next_level = models.IntegerField(default=10000)
    
    # User preferences
    ai_personality = models.CharField(max_length=20, choices=PERSONALITY_CHOICES, default='mentor')
    timezone = models.CharField(max_length=50, default='UTC')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} (Level {self.level} {self.character_class})"
    
    def get_total_stats(self):
        """Calculate total stat points"""
        return self.strength + self.intelligence + self.charisma + self.endurance + self.luck
    
    def add_xp(self, amount):
        """Add XP and handle level ups"""
        self.total_xp += amount
        while self.total_xp >= self.xp_to_next_level:
            self.level_up()
        self.save()
    
    def level_up(self):
        """Handle level up logic"""
        self.level += 1
        self.total_xp -= self.xp_to_next_level
        self.xp_to_next_level = int(self.xp_to_next_level * 1.2)  # Increase XP requirement
        # Bonus stats on level up
        self.strength += 1
        self.intelligence += 1
        self.charisma += 1
        self.endurance += 1
        self.luck += 1
        # Note: save() is called by add_xp() after all level ups


class Quest(models.Model):
    """AI-generated quests for users"""
    
    QUEST_TYPES = [
        ('daily', 'Daily Quest'),
        ('habit', 'Habit Quest'),
        ('challenge', 'Challenge Quest'),
        ('bonus', 'Bonus Quest'),
    ]
    
    DIFFICULTY_LEVELS = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
        ('epic', 'Epic'),
    ]
    
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='quests')
    title = models.CharField(max_length=200)
    description = models.TextField()
    quest_type = models.CharField(max_length=20, choices=QUEST_TYPES, default='daily')
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_LEVELS, default='medium')
    
    # Rewards
    reward_xp = models.IntegerField(default=10)
    reward_strength = models.IntegerField(default=0)
    reward_intelligence = models.IntegerField(default=0)
    reward_charisma = models.IntegerField(default=0)
    reward_endurance = models.IntegerField(default=0)
    reward_luck = models.IntegerField(default=0)
    
    # Status and timing
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # AI metadata
    generated_by_ai = models.BooleanField(default=True)
    ai_context = models.TextField(blank=True)  # Store AI reasoning/context
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} ({self.quest_type})"
    
    def complete_quest(self):
        """Mark quest as completed and award rewards"""
        if not self.completed:
            self.completed = True
            self.completed_at = timezone.now()
            
            # Award XP and stats (handle null values)
            xp_reward = self.reward_xp or 0
            self.profile.add_xp(xp_reward)
            
            # Add stat rewards (handle null values)
            self.profile.strength += (self.reward_strength or 0)
            self.profile.intelligence += (self.reward_intelligence or 0)
            self.profile.charisma += (self.reward_charisma or 0)
            self.profile.endurance += (self.reward_endurance or 0)
            self.profile.luck += (self.reward_luck or 0)
            self.profile.save()
            
            self.save()
            return True
        return False


class Habit(models.Model):
    """User habits tracked by the system"""
    
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('custom', 'Custom'),
    ]
    
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='habits')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='daily')
    
    # Tracking
    active = models.BooleanField(default=True)
    streak_count = models.IntegerField(default=0)
    total_completions = models.IntegerField(default=0)
    last_completed = models.DateTimeField(null=True, blank=True)
    
    # AI metadata
    created_from_chat = models.BooleanField(default=False)
    ai_suggested = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} (Streak: {self.streak_count})"
    
    def complete_today(self):
        """Mark habit as completed for today"""
        now = timezone.now()
        if self.last_completed and self.last_completed.date() == now.date():
            return False  # Already completed today
        
        # Update streak
        if self.last_completed and (now.date() - self.last_completed.date()).days == 1:
            self.streak_count += 1
        else:
            self.streak_count = 1
        
        self.last_completed = now
        self.total_completions += 1
        self.save()
        return True


class LogEntry(models.Model):
    """Log of user actions and stat changes"""
    
    ACTION_TYPES = [
        ('quest_completed', 'Quest Completed'),
        ('habit_completed', 'Habit Completed'),
        ('stat_change', 'Stat Change'),
        ('level_up', 'Level Up'),
        ('chat_interaction', 'Chat Interaction'),
    ]
    
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='log_entries')
    action_type = models.CharField(max_length=30, choices=ACTION_TYPES)
    action_description = models.TextField()
    
    # Stats before and after (JSON fields)
    stats_before = models.JSONField(default=dict)
    stats_after = models.JSONField(default=dict)
    
    # XP changes
    xp_gained = models.IntegerField(default=0)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.profile.name}: {self.action_description}"


class AIResponse(models.Model):
    """Store AI chat interactions and responses"""
    
    ROLE_CHOICES = [
        ('system', 'System'),
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]
    
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='ai_responses')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    
    # Metadata
    timestamp = models.DateTimeField(auto_now_add=True)
    tokens_used = models.IntegerField(default=0)
    
    # Action tracking
    triggered_action = models.CharField(max_length=100, blank=True)  # e.g., 'quest_complete', 'stat_update'
    action_data = models.JSONField(default=dict)  # Store parsed action data
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        return f"{self.profile.name} - {self.role}: {self.content[:50]}..."


class StatusEffect(models.Model):
    """Temporary buffs and debuffs for users"""
    
    EFFECT_TYPES = [
        ('buff', 'Buff'),
        ('debuff', 'Debuff'),
        ('neutral', 'Neutral'),
    ]
    
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='status_effects')
    name = models.CharField(max_length=100)
    description = models.TextField()
    effect_type = models.CharField(max_length=10, choices=EFFECT_TYPES, default='neutral')
    
    # Duration
    duration_hours = models.IntegerField(default=24)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    # Effects on stats (percentage modifiers)
    strength_modifier = models.FloatField(default=0.0)
    intelligence_modifier = models.FloatField(default=0.0)
    charisma_modifier = models.FloatField(default=0.0)
    endurance_modifier = models.FloatField(default=0.0)
    luck_modifier = models.FloatField(default=0.0)
    
    active = models.BooleanField(default=True)
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=self.duration_hours)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.name} ({self.effect_type})"
    
    @property
    def is_expired(self):
        return timezone.now() > self.expires_at
