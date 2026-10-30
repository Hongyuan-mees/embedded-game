/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usart.h"
#include "gpio.h"
#include "usb_device.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "usbd_cdc_interface.h"
#include <stdbool.h>
#include <math.h>
#include <stdio.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

#define MPU6050_DEFAULT_ADDRESS  0x68U
#define MPU6050_REG_ACCEL_XOUT_H 0x3BU
#define MPU6050_REG_CONFIG       0x1AU
#define MPU6050_REG_GYRO_CONFIG  0x1BU
#define MPU6050_REG_ACCEL_CONFIG 0x1CU
#define MPU6050_REG_PWR_MGMT_1   0x6BU
#define MPU6050_REG_WHO_AM_I     0x75U

#define I2C_SCL_PIN              GPIO_PIN_6
#define I2C_SDA_PIN              GPIO_PIN_7
#define I2C_GPIO_PORT            GPIOB
#define USE_HARDWARE_I2C         1
#define RUN_I2C_LOOPBACK_TEST    0

#define RAD_TO_DEG_F             57.2957795F
#define ACCEL_LSB_PER_G_F        16384.0F
#define ANGLE_FILTER_ALPHA_F     0.08F
#define JUMP_HIGH_THRESHOLD_G_F  1.18F
#define JUMP_LOW_THRESHOLD_G_F   0.82F
#define JUMP_PULSE_MS            300U
#define JUMP_COOLDOWN_MS         700U

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */

static uint8_t usb_message[160];
static uint8_t mpu6050_address = MPU6050_DEFAULT_ADDRESS;
static uint8_t i2c_external_pullup_mask = 0U;
static uint8_t i2c_loopback_mask = 0U;
#if USE_HARDWARE_I2C
static uint8_t i2c_scan_count = 0U;
static uint8_t i2c_first_address = 0U;
static I2C_HandleTypeDef hi2c1;
#endif

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */

static void Soft_I2C_Init(void);
#if USE_HARDWARE_I2C
static void Hardware_I2C_Init(void);
static void Hardware_I2C_Scan(void);
#endif
static bool MPU6050_Init(uint8_t *who_am_i);
static bool MPU6050_Read_Raw(int16_t *ax, int16_t *ay, int16_t *az,
                             int16_t *gx, int16_t *gy, int16_t *gz);
static void Motion_Update(int16_t ax, int16_t ay, int16_t az,
                          uint32_t current_tick, int16_t *roll_x10,
                          int16_t *pitch_x10, uint8_t *jump);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

#if 1
static void Soft_I2C_Delay(void)
{
  for (volatile uint32_t delay = 0U; delay < 300U; ++delay)
  {
    __NOP();
  }
}

static void Soft_I2C_Configure_Pin(uint16_t pin, uint32_t configuration)
{
  uint32_t shift = (pin == I2C_SCL_PIN) ? 24U : 28U;
  uint32_t crl = I2C_GPIO_PORT->CRL;
  crl &= ~(0x0FU << shift);
  crl |= (configuration << shift);
  I2C_GPIO_PORT->CRL = crl;
}

static void Soft_I2C_SDA_Low(void)
{
  I2C_GPIO_PORT->BRR = I2C_SDA_PIN;
  Soft_I2C_Configure_Pin(I2C_SDA_PIN, 0x07U); /* 50 MHz open-drain output. */
  I2C_GPIO_PORT->BRR = I2C_SDA_PIN;
}

static void Soft_I2C_SDA_Release(void)
{
  I2C_GPIO_PORT->BSRR = I2C_SDA_PIN;
  Soft_I2C_Configure_Pin(I2C_SDA_PIN, 0x08U); /* Input with internal pull-up. */
  I2C_GPIO_PORT->BSRR = I2C_SDA_PIN;
}

static void Soft_I2C_SCL_Low(void)
{
  I2C_GPIO_PORT->BRR = I2C_SCL_PIN;
  Soft_I2C_Configure_Pin(I2C_SCL_PIN, 0x07U); /* 50 MHz open-drain output. */
  I2C_GPIO_PORT->BRR = I2C_SCL_PIN;
}

static bool Soft_I2C_SCL_Release(void)
{
  I2C_GPIO_PORT->BSRR = I2C_SCL_PIN;
  Soft_I2C_Configure_Pin(I2C_SCL_PIN, 0x08U); /* Input with internal pull-up. */
  I2C_GPIO_PORT->BSRR = I2C_SCL_PIN;

  for (uint32_t timeout = 0U; timeout < 10000U; ++timeout)
  {
    if (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SCL_PIN) == GPIO_PIN_SET)
    {
      return true;
    }
  }

  return false;
}

static bool Soft_I2C_Start(void)
{
  Soft_I2C_SDA_Release();
  if (!Soft_I2C_SCL_Release())
  {
    return false;
  }

  Soft_I2C_Delay();
  if (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) != GPIO_PIN_SET)
  {
    return false;
  }

  Soft_I2C_SDA_Low();
  Soft_I2C_Delay();
  Soft_I2C_SCL_Low();
  Soft_I2C_Delay();
  return true;
}

static uint8_t I2C_Loopback_Run(void)
{
  uint8_t result = 0U;
  __HAL_RCC_GPIOB_CLK_ENABLE();

  Soft_I2C_SCL_Release();
  Soft_I2C_SDA_Release();
  HAL_Delay(10U);
  if ((HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SCL_PIN) == GPIO_PIN_SET) &&
      (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) == GPIO_PIN_SET))
  {
    result |= 0x01U;
  }

  Soft_I2C_SCL_Low();
  Soft_I2C_SDA_Release();
  HAL_Delay(10U);
  if (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) == GPIO_PIN_RESET)
  {
    result |= 0x02U;
  }

  Soft_I2C_SCL_Release();
  Soft_I2C_SDA_Low();
  HAL_Delay(10U);
  if (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SCL_PIN) == GPIO_PIN_RESET)
  {
    result |= 0x04U;
  }

  Soft_I2C_SCL_Release();
  Soft_I2C_SDA_Release();
  return result;
}

static void Soft_I2C_Stop(void)
{
  Soft_I2C_SDA_Low();
  Soft_I2C_Delay();
  (void)Soft_I2C_SCL_Release();
  Soft_I2C_Delay();
  Soft_I2C_SDA_Release();
  Soft_I2C_Delay();
}

static bool Soft_I2C_Write_Byte(uint8_t value)
{
  for (uint8_t bit = 0U; bit < 8U; ++bit)
  {
    if ((value & 0x80U) != 0U)
    {
      Soft_I2C_SDA_Release();
    }
    else
    {
      Soft_I2C_SDA_Low();
    }

    Soft_I2C_Delay();
    if (!Soft_I2C_SCL_Release())
    {
      return false;
    }
    Soft_I2C_Delay();
    Soft_I2C_SCL_Low();
    value <<= 1U;
  }

  Soft_I2C_SDA_Release();
  Soft_I2C_Delay();
  if (!Soft_I2C_SCL_Release())
  {
    return false;
  }

  Soft_I2C_Delay();
  bool acknowledged = (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) == GPIO_PIN_RESET);
  Soft_I2C_SCL_Low();
  Soft_I2C_Delay();
  return acknowledged;
}

static uint8_t Soft_I2C_Read_Byte(bool acknowledge)
{
  uint8_t value = 0U;
  Soft_I2C_SDA_Release();

  for (uint8_t bit = 0U; bit < 8U; ++bit)
  {
    value <<= 1U;
    Soft_I2C_Delay();
    if (!Soft_I2C_SCL_Release())
    {
      return 0U;
    }
    Soft_I2C_Delay();
    if (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) == GPIO_PIN_SET)
    {
      value |= 1U;
    }
    Soft_I2C_SCL_Low();
  }

  if (acknowledge)
  {
    Soft_I2C_SDA_Low();
  }
  else
  {
    Soft_I2C_SDA_Release();
  }

  Soft_I2C_Delay();
  (void)Soft_I2C_SCL_Release();
  Soft_I2C_Delay();
  Soft_I2C_SCL_Low();
  Soft_I2C_SDA_Release();
  Soft_I2C_Delay();
  return value;
}

static void Soft_I2C_Recover_Bus(void)
{
  Soft_I2C_SDA_Release();
  for (uint8_t pulse = 0U; pulse < 9U; ++pulse)
  {
    Soft_I2C_SCL_Low();
    Soft_I2C_Delay();
    (void)Soft_I2C_SCL_Release();
    Soft_I2C_Delay();
  }
  Soft_I2C_Stop();
}

static void Soft_I2C_Init(void)
{
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /* Weakly pull both lines down. A powered MPU6050 module with normal onboard
     I2C pull-ups should still make the corresponding input read high. */
  I2C_GPIO_PORT->BRR = I2C_SCL_PIN | I2C_SDA_PIN;
  Soft_I2C_Configure_Pin(I2C_SCL_PIN, 0x08U);
  Soft_I2C_Configure_Pin(I2C_SDA_PIN, 0x08U);
  HAL_Delay(10U);

  if (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SCL_PIN) == GPIO_PIN_SET)
  {
    i2c_external_pullup_mask |= 0x01U;
  }
  if (HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) == GPIO_PIN_SET)
  {
    i2c_external_pullup_mask |= 0x02U;
  }

  Soft_I2C_SCL_Release();
  Soft_I2C_SDA_Release();

  Soft_I2C_Recover_Bus();
}
#endif

#if USE_HARDWARE_I2C
static void Hardware_I2C_Init(void)
{
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 100000U;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0U;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0U;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;

  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
}

static void Hardware_I2C_Scan(void)
{
  i2c_scan_count = 0U;
  i2c_first_address = 0U;

  for (uint8_t address = 0x03U; address <= 0x77U; ++address)
  {
    if (HAL_I2C_IsDeviceReady(&hi2c1, (uint16_t)(address << 1U), 2U, 10U) == HAL_OK)
    {
      if (i2c_scan_count == 0U)
      {
        i2c_first_address = address;
      }
      ++i2c_scan_count;
    }
  }
}
#endif

static bool MPU6050_Write_Register(uint8_t reg, uint8_t value)
{
#if USE_HARDWARE_I2C
  return HAL_I2C_Mem_Write(&hi2c1,
                           (uint16_t)(mpu6050_address << 1U),
                           reg,
                           I2C_MEMADD_SIZE_8BIT,
                           &value,
                           1U,
                           100U) == HAL_OK;
#else
  if (!Soft_I2C_Start())
  {
    Soft_I2C_Stop();
    return false;
  }

  if (!Soft_I2C_Write_Byte((uint8_t)(mpu6050_address << 1U)) ||
      !Soft_I2C_Write_Byte(reg) ||
      !Soft_I2C_Write_Byte(value))
  {
    Soft_I2C_Stop();
    return false;
  }

  Soft_I2C_Stop();
  return true;
#endif
}

static bool MPU6050_Read_Registers(uint8_t reg, uint8_t *data, uint8_t length)
{
  if ((data == NULL) || (length == 0U))
  {
    return false;
  }

#if USE_HARDWARE_I2C
  return HAL_I2C_Mem_Read(&hi2c1,
                          (uint16_t)(mpu6050_address << 1U),
                          reg,
                          I2C_MEMADD_SIZE_8BIT,
                          data,
                          length,
                          100U) == HAL_OK;
#else
  if (!Soft_I2C_Start())
  {
    Soft_I2C_Stop();
    return false;
  }

  if (!Soft_I2C_Write_Byte((uint8_t)(mpu6050_address << 1U)) ||
      !Soft_I2C_Write_Byte(reg) ||
      !Soft_I2C_Start() ||
      !Soft_I2C_Write_Byte((uint8_t)((mpu6050_address << 1U) | 0x01U)))
  {
    Soft_I2C_Stop();
    return false;
  }

  for (uint8_t index = 0U; index < length; ++index)
  {
    data[index] = Soft_I2C_Read_Byte(index < (uint8_t)(length - 1U));
  }

  Soft_I2C_Stop();
  return true;
#endif
}

static bool MPU6050_Init(uint8_t *who_am_i)
{
  uint8_t identity = 0U;

  mpu6050_address = 0x68U;
  bool identified = MPU6050_Read_Registers(MPU6050_REG_WHO_AM_I, &identity, 1U);

  if (!identified)
  {
    mpu6050_address = 0x69U;
    identified = MPU6050_Read_Registers(MPU6050_REG_WHO_AM_I, &identity, 1U);
  }

  if (!identified)
  {
    if (who_am_i != NULL)
    {
      *who_am_i = 0U;
    }
    return false;
  }

  if (who_am_i != NULL)
  {
    *who_am_i = identity;
  }

  /* Some MPU-6050-compatible breakout boards report 0x74 while keeping the
     MPU-6050 I2C address and register map.  Accept it for the data-path test;
     the raw readings below are the final compatibility check. */
  if ((identity != 0x68U) && (identity != 0x74U))
  {
    return false;
  }

  if (!MPU6050_Write_Register(MPU6050_REG_PWR_MGMT_1, 0x01U))
  {
    return false;
  }
  HAL_Delay(100U);

  return MPU6050_Write_Register(MPU6050_REG_CONFIG, 0x03U) &&
         MPU6050_Write_Register(MPU6050_REG_GYRO_CONFIG, 0x00U) &&
         MPU6050_Write_Register(MPU6050_REG_ACCEL_CONFIG, 0x00U);
}

static bool MPU6050_Read_Raw(int16_t *ax, int16_t *ay, int16_t *az,
                             int16_t *gx, int16_t *gy, int16_t *gz)
{
  uint8_t raw[14];
  if (!MPU6050_Read_Registers(MPU6050_REG_ACCEL_XOUT_H, raw, sizeof(raw)))
  {
    return false;
  }

  *ax = (int16_t)(((uint16_t)raw[0] << 8U) | raw[1]);
  *ay = (int16_t)(((uint16_t)raw[2] << 8U) | raw[3]);
  *az = (int16_t)(((uint16_t)raw[4] << 8U) | raw[5]);
  *gx = (int16_t)(((uint16_t)raw[8] << 8U) | raw[9]);
  *gy = (int16_t)(((uint16_t)raw[10] << 8U) | raw[11]);
  *gz = (int16_t)(((uint16_t)raw[12] << 8U) | raw[13]);
  return true;
}

static void Motion_Update(int16_t ax, int16_t ay, int16_t az,
                          uint32_t current_tick, int16_t *roll_x10,
                          int16_t *pitch_x10, uint8_t *jump)
{
  static bool filter_initialized = false;
  static float filtered_roll = 0.0F;
  static float filtered_pitch = 0.0F;
  static uint32_t jump_output_until = 0U;
  static uint32_t jump_rearm_tick = 0U;

  float ax_f = (float)ax;
  float ay_f = (float)ay;
  float az_f = (float)az;
  float roll = atan2f(ay_f, az_f) * RAD_TO_DEG_F;
  float pitch = atan2f(-ax_f, sqrtf((ay_f * ay_f) + (az_f * az_f))) * RAD_TO_DEG_F;

  if (!filter_initialized)
  {
    filtered_roll = roll;
    filtered_pitch = pitch;
    filter_initialized = true;
  }
  else
  {
    float roll_delta = roll - filtered_roll;
    if (roll_delta > 180.0F)
    {
      roll_delta -= 360.0F;
    }
    else if (roll_delta < -180.0F)
    {
      roll_delta += 360.0F;
    }

    filtered_roll += ANGLE_FILTER_ALPHA_F * roll_delta;
    if (filtered_roll > 180.0F)
    {
      filtered_roll -= 360.0F;
    }
    else if (filtered_roll < -180.0F)
    {
      filtered_roll += 360.0F;
    }
    filtered_pitch += ANGLE_FILTER_ALPHA_F * (pitch - filtered_pitch);
  }

  float acceleration_g = sqrtf((ax_f * ax_f) + (ay_f * ay_f) + (az_f * az_f)) /
                         ACCEL_LSB_PER_G_F;
  bool jump_rearmed = ((int32_t)(current_tick - jump_rearm_tick) >= 0);
  if (jump_rearmed &&
      ((acceleration_g > JUMP_HIGH_THRESHOLD_G_F) ||
       (acceleration_g < JUMP_LOW_THRESHOLD_G_F)))
  {
    jump_output_until = current_tick + JUMP_PULSE_MS;
    jump_rearm_tick = current_tick + JUMP_COOLDOWN_MS;
  }

  float roll_scaled = filtered_roll * 10.0F;
  float pitch_scaled = filtered_pitch * 10.0F;
  *roll_x10 = (int16_t)(roll_scaled >= 0.0F ? roll_scaled + 0.5F : roll_scaled - 0.5F);
  *pitch_x10 = (int16_t)(pitch_scaled >= 0.0F ? pitch_scaled + 0.5F : pitch_scaled - 0.5F);
  *jump = ((int32_t)(jump_output_until - current_tick) > 0) ? 1U : 0U;
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART1_UART_Init();
  MX_USB_DEVICE_Init();
  /* USER CODE BEGIN 2 */
  uint8_t who_am_i = 0U;
  bool mpu6050_ready = false;
  bool first_status_pending = true;
  uint32_t last_usb_message_tick = HAL_GetTick();

  if (RUN_I2C_LOOPBACK_TEST)
  {
    i2c_loopback_mask = I2C_Loopback_Run();
  }
  else
  {
#if USE_HARDWARE_I2C
  Hardware_I2C_Init();
  HAL_Delay(500U);
  Hardware_I2C_Scan();
#else
  Soft_I2C_Init();
  HAL_Delay(500U);
#endif
    mpu6050_ready = MPU6050_Init(&who_am_i);
  }
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    uint32_t current_tick = HAL_GetTick();

    if (RUN_I2C_LOOPBACK_TEST)
    {
      if ((current_tick - last_usb_message_tick) >= 1000U)
      {
        int message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                      "I2C_LOOPBACK,HIGH:%u,SCL_TO_SDA:%u,SDA_TO_SCL:%u,RESULT:%s\r\n",
                                      (i2c_loopback_mask & 0x01U) != 0U,
                                      (i2c_loopback_mask & 0x02U) != 0U,
                                      (i2c_loopback_mask & 0x04U) != 0U,
                                      i2c_loopback_mask == 0x07U ? "PASS" : "FAIL");
        if ((message_length > 0) &&
            (CDC_Transmit_FS(usb_message, (uint16_t)message_length) == USBD_OK))
        {
          last_usb_message_tick = current_tick;
        }
      }
      continue;
    }

    uint32_t message_period = mpu6050_ready ? 20U : 1000U;

    if ((current_tick - last_usb_message_tick) >= message_period)
    {
      int message_length = 0;

      if (first_status_pending)
      {
        if (mpu6050_ready)
        {
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "Motion Controller Ready,MPU6050_OK,ADDR:0x%02X,WHO_AM_I:0x%02X\r\n",
                                    mpu6050_address, who_am_i);
        }
        else
        {
#if USE_HARDWARE_I2C
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "MPU6050_ERROR,HW_SCAN_COUNT:%u,FIRST:0x%02X,WHO:0x%02X\r\n",
                                    i2c_scan_count, i2c_first_address, who_am_i);
#else
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "MPU6050_ERROR,SOFT_I2C_PULLUP,SCL:%u,SDA:%u,WHO:0x%02X\r\n",
                                    HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SCL_PIN) == GPIO_PIN_SET,
                                    HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) == GPIO_PIN_SET,
                                    who_am_i);
#endif
        }
        first_status_pending = false;
      }
      else if (mpu6050_ready)
      {
        int16_t ax = 0;
        int16_t ay = 0;
        int16_t az = 0;
        int16_t gx = 0;
        int16_t gy = 0;
        int16_t gz = 0;

        if (MPU6050_Read_Raw(&ax, &ay, &az, &gx, &gy, &gz))
        {
          int16_t roll_x10 = 0;
          int16_t pitch_x10 = 0;
          uint8_t jump = 0U;
          Motion_Update(ax, ay, az, current_tick, &roll_x10, &pitch_x10, &jump);

          int32_t roll_abs = (roll_x10 < 0) ? -(int32_t)roll_x10 : (int32_t)roll_x10;
          int32_t pitch_abs = (pitch_x10 < 0) ? -(int32_t)pitch_x10 : (int32_t)pitch_x10;
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "ROLL:%s%ld.%01ld,PITCH:%s%ld.%01ld,JUMP:%u\r\n",
                                    roll_x10 < 0 ? "-" : "",
                                    (long)(roll_abs / 10), (long)(roll_abs % 10),
                                    pitch_x10 < 0 ? "-" : "",
                                    (long)(pitch_abs / 10), (long)(pitch_abs % 10),
                                    jump);
        }
        else
        {
          mpu6050_ready = false;
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "MPU6050_ERROR,I2C_READ_FAILED\r\n");
        }
      }
      else
      {
#if USE_HARDWARE_I2C
        (void)HAL_I2C_DeInit(&hi2c1);
        Hardware_I2C_Init();
        HAL_Delay(20U);
        Hardware_I2C_Scan();
#else
        Soft_I2C_Init();
        HAL_Delay(20U);
#endif
        mpu6050_ready = MPU6050_Init(&who_am_i);
        if (mpu6050_ready)
        {
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "MPU6050_OK,ADDR:0x%02X,WHO_AM_I:0x%02X\r\n",
                                    mpu6050_address, who_am_i);
        }
        else
        {
#if USE_HARDWARE_I2C
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "MPU6050_ERROR,HW_SCAN_COUNT:%u,FIRST:0x%02X,WHO:0x%02X\r\n",
                                    i2c_scan_count, i2c_first_address, who_am_i);
#else
          message_length = snprintf((char *)usb_message, sizeof(usb_message),
                                    "MPU6050_ERROR,SOFT_I2C_PULLUP,SCL:%u,SDA:%u,WHO:0x%02X\r\n",
                                    HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SCL_PIN) == GPIO_PIN_SET,
                                    HAL_GPIO_ReadPin(I2C_GPIO_PORT, I2C_SDA_PIN) == GPIO_PIN_SET,
                                    who_am_i);
#endif
        }
      }

      if ((message_length > 0) &&
          (CDC_Transmit_FS(usb_message, (uint16_t)message_length) == USBD_OK))
      {
        last_usb_message_tick = current_tick;
      }
    }
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInit = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.HSEPredivValue = RCC_HSE_PREDIV_DIV1;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL9;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }

  PeriphClkInit.PeriphClockSelection = RCC_PERIPHCLK_USB;
  PeriphClkInit.UsbClockSelection = RCC_USBCLKSOURCE_PLL_DIV1_5;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInit) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
