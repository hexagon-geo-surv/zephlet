if(CONFIG_ZEPHLET_QUIET)
    zephyr_zephlet_generate(
        TYPE    quiet
        PREFIX  zlet_quiet
        SOURCES zlet_quiet.c)
endif()
