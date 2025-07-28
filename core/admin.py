from django.contrib import admin
from .models import Profile, Quest, Habit, LogEntry, AIResponse, StatusEffect


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'level', 'character_class', 'get_total_stats', 'last_active')
    list_filter = ('level', 'character_class', 'avatar', 'ai_personality')
    search_fields = ('name', 'user__username', 'user__email')
    readonly_fields = ('total_xp', 'created_at', 'last_active')
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'name', 'avatar', 'character_class', 'ai_personality')
        }),
        ('Stats & Level', {
            'fields': ('level', 'total_xp', 'xp_to_next_level', 'strength', 'intelligence', 'charisma', 'endurance', 'luck')
        }),
        ('Metadata', {
            'fields': ('timezone', 'created_at', 'last_active'),
            'classes': ('collapse',)
        })
    )


@admin.register(Quest)
class QuestAdmin(admin.ModelAdmin):
    list_display = ('title', 'profile', 'quest_type', 'difficulty', 'completed', 'reward_xp', 'created_at')
    list_filter = ('quest_type', 'difficulty', 'completed', 'generated_by_ai')
    search_fields = ('title', 'description', 'profile__name')
    readonly_fields = ('completed_at', 'created_at')
    
    fieldsets = (
        ('Quest Info', {
            'fields': ('profile', 'title', 'description', 'quest_type', 'difficulty')
        }),
        ('Rewards', {
            'fields': ('reward_xp', 'reward_strength', 'reward_intelligence', 'reward_charisma', 'reward_endurance', 'reward_luck')
        }),
        ('Status', {
            'fields': ('completed', 'completed_at', 'due_date')
        }),
        ('AI Data', {
            'fields': ('generated_by_ai', 'ai_context'),
            'classes': ('collapse',)
        })
    )


@admin.register(Habit)
class HabitAdmin(admin.ModelAdmin):
    list_display = ('name', 'profile', 'frequency', 'streak_count', 'total_completions', 'active', 'last_completed')
    list_filter = ('frequency', 'active', 'created_from_chat', 'ai_suggested')
    search_fields = ('name', 'description', 'profile__name')
    readonly_fields = ('created_at',)


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ('profile', 'action_type', 'action_description', 'xp_gained', 'timestamp')
    list_filter = ('action_type', 'timestamp')
    search_fields = ('profile__name', 'action_description')
    readonly_fields = ('timestamp',)
    
    def has_add_permission(self, request):
        return False  # Log entries should only be created programmatically


@admin.register(AIResponse)
class AIResponseAdmin(admin.ModelAdmin):
    list_display = ('profile', 'role', 'content_preview', 'timestamp', 'tokens_used')
    list_filter = ('role', 'timestamp')
    search_fields = ('profile__name', 'content')
    readonly_fields = ('timestamp',)
    
    def content_preview(self, obj):
        return obj.content[:100] + "..." if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Content Preview'


@admin.register(StatusEffect)
class StatusEffectAdmin(admin.ModelAdmin):
    list_display = ('name', 'profile', 'effect_type', 'active', 'created_at', 'expires_at', 'is_expired')
    list_filter = ('effect_type', 'active', 'created_at')
    search_fields = ('name', 'profile__name', 'description')
    readonly_fields = ('created_at', 'is_expired')
    
    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = 'Expired'
